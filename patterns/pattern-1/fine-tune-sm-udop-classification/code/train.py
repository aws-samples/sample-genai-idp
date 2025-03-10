import argparse
import json
import os
import shutil
import torch

import lightning.pytorch as pl
import numpy as np

from lightning.pytorch.callbacks import ModelCheckpoint
from lightning.pytorch.callbacks.early_stopping import EarlyStopping
from lightning.pytorch.loggers import TensorBoardLogger 
from torch.utils.data import DataLoader
from transformers import AutoProcessor

from model import UDOPModel
from utils import ClassificationDataset


def train(
    data_dir, model_dir, script_dir, output_dir, max_epochs, accumulate_grad_batches, 
    devices, base_model, lr, lr_warmup_steps, dropout_rate, b1, b2, weight_decay,
    print_every_n_steps, patience, fast_dev_run, precision, distributed_strategy
):
    shutil.copytree(script_dir, os.path.join(model_dir, "code"), dirs_exist_ok=True)
    tb_logger = TensorBoardLogger(
        save_dir=os.path.join(output_dir, "tensorboard"),
        name="training_logs"
    )
    processor = AutoProcessor.from_pretrained(base_model, apply_ocr=False)
    train_ds = ClassificationDataset(processor, data_dir, split="training")
    val_ds = ClassificationDataset(processor, data_dir, split="validation")

    assert train_ds.prompt.strip() == val_ds.prompt.strip(), ( # nosec B101
        "Prompts do not match in training and validation dataset!\nTraining Prompt: {0}\nValidation Prompt: {1}".format(
            train_ds.prompt, val_ds.prompt
        )
    )

    train_dl = DataLoader(
        train_ds, batch_size=1, num_workers=4,
        collate_fn=lambda x: x[0], shuffle=True
    )
    val_dl = DataLoader(
        val_ds, batch_size=1, num_workers=4, 
        collate_fn=lambda x: x[0], shuffle=True
    )

    max_steps = (
        (max_epochs * len(train_ds)) // accumulate_grad_batches // devices
    )

    model = UDOPModel(
        model_id=base_model,
        lr=lr, lr_warmup_steps=lr_warmup_steps,
        dropout_rate=dropout_rate, max_steps=max_steps,
        b1=b1, b2=b2, weight_decay=weight_decay,
        print_every_n_steps=print_every_n_steps
    )

    callbacks = []
    callbacks.append(ModelCheckpoint(
        monitor="val_weighted_avg_f1", mode="max", save_top_k=1,
        filename='best_model', dirpath=model_dir,  verbose=True
    ))
    callbacks.append(EarlyStopping(
        monitor="val_weighted_avg_f1", mode="max", patience=patience,
    ))

    trainer = pl.Trainer(
        max_epochs=max_epochs,
        log_every_n_steps=1,
        accelerator="gpu",
        fast_dev_run=fast_dev_run,
        devices=devices,
        callbacks=callbacks,
        accumulate_grad_batches=accumulate_grad_batches,
        logger=tb_logger,
        precision=precision,
        strategy=distributed_strategy
    )
    trainer.fit(model, train_dataloaders=train_dl, val_dataloaders=val_dl)
    metrics = trainer.callback_metrics
    final_metrics = {k: v.item() for k, v in metrics.items()}

    metrics_filename = os.path.join(output_dir, "data/training_metrics.json")
    with open(metrics_filename, "w") as f:
        json.dump(final_metrics, f)

    prompt_filename = os.path.join(model_dir, "validation_prompt.json")
    with open(prompt_filename, "w") as f:
        json.dump({"validation_prompt": train_ds.prompt}, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data_dir", type=str,
        default=os.environ.get("SM_INPUT_DIR", "/opt/ml/input") + "/data"
    )
    parser.add_argument(
        "--model_dir", type=str,
        default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
    )
    parser.add_argument(
        "--script_dir", type=str,
        default=os.environ.get("SM_SCRIPT_DIR", "/opt/ml/code")
    )
    parser.add_argument(
        "--output_dir", type=str,
        default=os.environ.get("SM_OUTPUT_DIR", "/opt/ml/output")
    )
    parser.add_argument("--base_model", type=str, default="microsoft/udop-large")
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--b1", type=float, default=0.9)
    parser.add_argument("--b2", type=float, default=0.999)
    parser.add_argument("--weight_decay", type=float, default=1e-4)
    parser.add_argument("--lr_warmup_steps", type=int, default=60)
    parser.add_argument("--max_epochs", type=int, default=3)
    parser.add_argument("--accumulate_grad_batches", type=int, default=10)
    parser.add_argument("--devices", type=int, default=torch.cuda.device_count())
    parser.add_argument("--dropout_rate", type=float, default=0.2)
    parser.add_argument("--precision", type=str, default="bf16-true")
    parser.add_argument("--distributed_strategy", type=str, default="ddp_find_unused_parameters_true")
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--fast_dev_run", type=int, default=None)
    parser.add_argument("--print_every_n_steps", type=int, default=100)

    args = parser.parse_args()
    train(
        args.data_dir, args.model_dir, args.script_dir, args.output_dir, 
        args.max_epochs, args.accumulate_grad_batches, args.devices, 
        args.base_model, args.lr, args.lr_warmup_steps, args.dropout_rate, 
        args.b1, args.b2, args.weight_decay, args.print_every_n_steps, 
        args.patience, args.fast_dev_run, args.precision, args.distributed_strategy
    )