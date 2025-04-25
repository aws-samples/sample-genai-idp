"""
Metrics calculation for document evaluation.

This module provides functions to calculate various evaluation metrics.
"""

from typing import Dict, List, Any


def precision(tp: int, fp: int) -> float:
    """
    Calculate precision metric.
    
    Precision is the ratio of correctly predicted positive observations to the 
    total predicted positives.
    
    Args:
        tp: Number of true positives
        fp: Number of false positives
        
    Returns:
        Precision score between 0.0 and 1.0
    """
    return tp / (tp + fp) if tp + fp > 0 else 0.0


def recall(tp: int, fn: int) -> float:
    """
    Calculate recall metric.
    
    Recall is the ratio of correctly predicted positive observations to all
    actual positives.
    
    Args:
        tp: Number of true positives
        fn: Number of false negatives
        
    Returns:
        Recall score between 0.0 and 1.0
    """
    return tp / (tp + fn) if tp + fn > 0 else 0.0


def f1_score(prec: float, rec: float) -> float:
    """
    Calculate F1 score.
    
    F1 Score is the weighted average of precision and recall.
    
    Args:
        prec: Precision score
        rec: Recall score
        
    Returns:
        F1 score between 0.0 and 1.0
    """
    return 2 * (prec * rec) / (prec + rec) if prec + rec > 0 else 0.0


def accuracy(tp: int, fp: int, fn: int, tn: int) -> float:
    """
    Calculate accuracy metric.
    
    Accuracy is the ratio of correctly predicted observations to the total observations.
    
    Args:
        tp: Number of true positives
        fp: Number of false positives
        fn: Number of false negatives
        tn: Number of true negatives
        
    Returns:
        Accuracy score between 0.0 and 1.0
    """
    return (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0.0


def false_alarm_rate(fp1: int, tn: int) -> float:
    """
    Calculate false alarm rate.
    
    False alarm rate is the proportion of false positives out of the 
    total negative instances.
    
    Args:
        fp1: Number of type 1 false positives (predicted when should be absent)
        tn: Number of true negatives
        
    Returns:
        False alarm rate between 0.0 and 1.0
    """
    return fp1 / (fp1 + tn) if fp1 + tn > 0 else 0.0


def false_discovery_rate(fp2: int, tp: int) -> float:
    """
    Calculate false discovery rate.
    
    False discovery rate is the proportion of false positives among all positive predictions.
    
    Args:
        fp2: Number of type 2 false positives (predicted wrong value)
        tp: Number of true positives
        
    Returns:
        False discovery rate between 0.0 and 1.0
    """
    return fp2 / (fp2 + tp) if fp2 + tp > 0 else 0.0


def calculate_metrics(tp: int, fp: int, fn: int, tn: int = 0, fp1: int = 0, fp2: int = 0) -> Dict[str, float]:
    """
    Calculate comprehensive evaluation metrics.
    
    Args:
        tp: Number of true positives
        fp: Number of false positives
        fn: Number of false negatives
        tn: Number of true negatives (optional)
        fp1: Number of type 1 false positives - predicted when should be absent (optional)
        fp2: Number of type 2 false positives - predicted wrong value (optional)
        
    Returns:
        Dictionary of metrics
    """
    prec = precision(tp, fp)
    rec = recall(tp, fn)
    f1 = f1_score(prec, rec)
    acc = accuracy(tp, fp, fn, tn)
    far = false_alarm_rate(fp1, tn)
    fdr = false_discovery_rate(fp2, tp)
    
    return {
        "precision": prec,
        "recall": rec,
        "f1_score": f1,
        "accuracy": acc,
        "false_alarm_rate": far,
        "false_discovery_rate": fdr
    }