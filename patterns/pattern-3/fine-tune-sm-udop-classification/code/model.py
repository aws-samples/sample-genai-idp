import torch

import lightning.pytorch as pl

from transformers import UdopForConditionalGeneration
from transformers.optimization import get_cosine_schedule_with_warmup


class UDOPModel(pl.LightningModule):
    def __init__(
        self, model_id, lr=5e-5, weight_decay=1e-5, b1=0.9, b2=0.999, 
        lr_warmup_steps=20, max_steps=5000, dropout_rate=0.2,
        print_every_n_steps=100
    ):
        super().__init__()
        self.lr = lr
        self.b1 = b1
        self.b2 = b2
        self.weight_decay = weight_decay
        self.lr_warmup_steps = lr_warmup_steps
        self.max_steps = max_steps
        self.print_every_n_steps = print_every_n_steps
        self.model = UdopForConditionalGeneration.from_pretrained(
            model_id, dropout_rate=dropout_rate
        )
        self.training_step_outputs = []
        self.validation_step_outputs = []
        self.tasks = {}

    def predict_step(self, batch, batch_idx, dataloader_idx=0):
        return batch['evaluator'].decode_model_output(
            self.model.forward(**batch['model_inputs'])
        )

    def generic_step(self, batch, batch_idx, subset='train'):
        after_mem = torch.cuda.memory_allocated(device=None)

        # Log memory usage and lr
        self.log("memory_usage_gb", after_mem/1e9, prog_bar=False)
        self.log("lr_times_1m", self.scheduler.get_lr()[0] * 1000000, prog_bar=True)

        try:
            model_output = self.model.forward(**batch['model_inputs'])
            lss = batch['evaluator'].compute_loss(batch, model_output)
            self.log(f"{subset}_loss", lss, sync_dist=True, prog_bar=True)
        except torch.cuda.OutOfMemoryError as e:
            print(str(e))
            for k, v in batch['model_inputs'].items():
                print(f"{k}, of shape {v.shape}")
            lss = torch.tensor(0)

        self.tasks.setdefault(batch['task'], batch['evaluator'])
        step_outputs = {
            "model_output": batch['evaluator'].decode_model_output(model_output),
            "targets": batch['text_label'],
            "task": batch['task']
        }
        return step_outputs, lss

    def training_step(self, batch, batch_idx):
        step_outputs, lss = self.generic_step(batch, batch_idx, subset='train')
        self.training_step_outputs.append(step_outputs)
        return lss

    def validation_step(self, batch, batch_idx):
        step_outputs, lss = self.generic_step(batch, batch_idx, subset='val')
        self.validation_step_outputs.append(step_outputs)
        return lss

    def on_train_epoch_end(self):
        d = {t: {
            'predictions': [o['model_output'] for o in self.training_step_outputs if o['task'] == t],
            'targets': [o['targets'] for o in self.training_step_outputs if o['task'] == t]
        } for t in self.tasks.keys()}
        for k, v in d.items():
            evaluator = self.tasks[k]
            metrics = evaluator.compute_metrics(v['predictions'], v['targets'])
            for k_, v_ in metrics.items():
                self.log(f"train_{k_}", v_, sync_dist=True, prog_bar=True)
        self.training_step_outputs.clear()

    def on_validation_epoch_end(self):
        # need to make sure we have elements in the list before we evaluate
        d = {t: {
            'predictions': [o['model_output'] for o in self.validation_step_outputs if o['task'] == t], 
            'targets': [o['targets'] for o in self.validation_step_outputs if o['task'] == t]
        } for t in self.tasks.keys()}
        for k, v in d.items():
            evaluator = self.tasks[k]
            metrics = evaluator.compute_metrics(v['predictions'], v['targets'])
            for k_, v_ in metrics.items():
                self.log(f"val_{k_}", v_, sync_dist=True, prog_bar=True)
        self.validation_step_outputs.clear()

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
            betas=(self.b1, self.b2)
        )
        scheduler = get_cosine_schedule_with_warmup(
            optimizer, num_warmup_steps=self.lr_warmup_steps,
            num_training_steps=self.max_steps
        )
        self.scheduler = scheduler
        return [optimizer], [{"scheduler": scheduler, "interval": "step"}] # Update LR in each step, not epoch