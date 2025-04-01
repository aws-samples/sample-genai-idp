import boto3
import json
import torch

import numpy as np

from PIL import Image
from sklearn.metrics import classification_report
from textractor.parsers import response_parser
from torch.nn import CrossEntropyLoss
from torch.utils.data import Dataset


def get_words_in_order(doc):
    """
        Helper method to get words from textract document in order 
        (left to right, top to bottom)
    """
    words = []
    for page in doc.pages:
        for line in page.lines:
            for word in line.words:
                words.append(word)
    return words


def get_boxes_from_textract(textract, model_norm_dim=1000):
    """
        Gets the bounding boxes and words from the textract output
    """
    doc = response_parser.parse(textract)
    words = get_words_in_order(doc)
    if len(words) == 0:
        return {'boxes': None, 'words': []}
    boxes = []
    texts = []
    for word in words:
        boxes.append(word.bbox.as_denormalized_numpy())
        texts.append(word.text)
    boxes = np.array(boxes)
    boxes[:, 2] += boxes[:, 0]
    boxes[:, 3] += boxes[:, 1]
    boxes[:, [1, 3]] /= doc.pages[0].height
    boxes[:, [0, 2]] /= doc.pages[0].width
    boxes *= model_norm_dim
    return {'boxes': np.array(boxes), 'words': texts}


class InferenceHelper():
    def __init__(self):
        self.s3_client = boto3.client('s3')

    def _get_image_from_s3(self, image_location):
        bucket, key = image_location[5:].split("/", 1)
        response = self.s3_client.get_object(Bucket=bucket, Key=key)
        image = np.array(Image.open(response["Body"]))
        # let's convert this from one channel to three channel if needed. 
        if len(image.shape) == 2:
            image = np.stack([image for i in range(3)], axis=-1)
        return image

    def _get_json_from_s3(self, json_location):
        bucket, key = json_location[5:].split("/", 1)
        response = self.s3_client.get_object(Bucket=bucket, Key=key)
        textract = json.loads(response["Body"].read())
        return textract

    def prepare_model_input(self, processor, image, textract, prompt):
        # process the textract object
        textract = get_boxes_from_textract(textract)

        prompt_words = prompt.split(" ")
        prompt_boxes = np.array([[0, 0, 0, 0] for _ in prompt_words])

        encoding = processor(
            images=image,
            text=prompt_words + textract['words'], 
            boxes=prompt_boxes if textract['boxes'] is None \
                else np.concatenate([prompt_boxes, textract['boxes']]),
            truncation=True,
            max_length=1024,
            return_tensors="pt",
        )
        return encoding


class DocClassificationEvaluator:
    """
    Document Classification Evaluator
    """

    def __init__(self, processor):
        self.loss_fn = CrossEntropyLoss(ignore_index=-100, reduction="none")
        self.processor = processor

    def decode_model_output(self, model_output, skip_special_tokens=True):
        logits = model_output["logits"]
        predicted_ids = torch.argmax(logits, dim=-1)
        string = self.processor.batch_decode(
            predicted_ids, skip_special_tokens=skip_special_tokens
        )[0]
        return string

    def compute_loss(self, model_input, model_output):
        return model_output.loss

    def compute_metrics(self, predictions, targets):
        labels = list(set(targets))
        report = classification_report(
            predictions, targets, output_dict=True, labels=labels
        )
        results = {}
        for label in labels:
            results[f"{label}_precision"] = report[label]["precision"]
            results[f"{label}_recall"] = report[label]["recall"]
            results[f"{label}_f1_score"] = report[label]["f1-score"]

        results["macro_avg_f1"] = report["macro avg"]["f1-score"]
        results["weighted_avg_f1"] = report["weighted avg"]["f1-score"]
        return results


class ClassificationDataset(Dataset):
    def __init__(self, processor, data_dir, split="training"):
        self.processor = processor
        self.data_dir = data_dir + '/' + split
        self.evaluator = DocClassificationEvaluator(processor=self.processor)
        with open(self.data_dir + '/metadata.json', 'r') as jfile:
            metadata = json.load(jfile)
        self.prompt = "Document Classification on {}.".format(
            metadata.get('name', 'ClassificationDataset')
        )
        self._size = int(metadata['size'])

    def prepare_input(self, image, textract, label):
        textract = get_boxes_from_textract(textract)
        prompt_words = self.prompt.split(" ")
        prompt_boxes = np.array([[0, 0, 0, 0] for _ in prompt_words])
        return {
            "prompt": self.prompt,
            "text_target": label,
            "boxes": prompt_boxes if textract['boxes'] is None else np.concatenate(
                [prompt_boxes, textract['boxes']]
                ),
            "text":  prompt_words + textract['words'],
            "image": np.stack([np.array(image) for _ in range(3)], axis=-1),
            "return_tensors": "pt",
        }

    def __len__(self):
        return self._size

    def __getitem__(self, idx):
        batch = self.prepare_input(
            self._load_data('images', idx),
            self._load_data('textract', idx),
            self._load_data('labels', idx),
        )
        # https://github.com/huggingface/transformers/blob/main/src/transformers/models/udop/processing_udop.py#L86
        # https://github.com/huggingface/transformers/blob/main/src/transformers/models/udop/processing_udop.py#L55
        encoding = self.processor(
            images=batch["image"], text=batch["text"], boxes=batch["boxes"],
            truncation=True, max_length=1024, return_tensors=batch['return_tensors']
        )
        target_encodings = self.processor(
            images=batch["image"], boxes=batch["boxes"],
            text_target=batch["text_target"], return_tensors=batch['return_tensors']
        )
        encoding["labels"] = target_encodings['input_ids']
        return {
            "model_inputs": encoding,
            "encoded_label": target_encodings['input_ids'],
            "prompt": batch["prompt"],
            "text_label": batch["text_target"],
            "evaluator": self.evaluator,
            "task": "document_classification",
        }

    def _load_data(self, datatype, idx):
        if datatype == 'textract':
            with open(self.data_dir + '/{}/{}.json'.format(datatype, idx), "r", encoding='utf-8') as f:
                return json.load(f)
        elif datatype == 'images':
            return Image.open(self.data_dir + '/{}/{}.png'.format(datatype, idx))
        elif datatype == 'labels':
            with open(self.data_dir + '/{}/{}.json'.format(datatype, idx), "r", encoding='utf-8') as f:
                return json.load(f)['label']