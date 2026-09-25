# Synthetic Document Classification Dataset

This directory contains a synthetically generated dataset for training the document classifier (`po`, `invoice`, `quote`).

## Background

To bootstrap our ML document classification without relying exclusively on keyword matching, we needed a labeled dataset. While there are several excellent public datasets for document classification and OCR on Hugging Face, **no public dataset includes 'vendor quote'**, so this dataset is purely synthetic.

## Hugging Face Datasets

The following Hugging Face datasets are compatible and can be loaded via the `datasets` library for additional real-world `invoice` or `po` samples if needed in the future:
- `AyoubChLin/CompanyDocuments`
- `AyoubChLin/northwind_PurchaseOrders`
- `mychen76/invoices-and-receipts_ocr_v1`
- `Voxel51/high-quality-invoice-images-for-ocr`
- `priyank-m/SROIE_2019_text_recognition`

## Structure

- `classification_training_data.csv`: A CSV containing `text` and `label` columns.
- The `generate_classification_dataset.py` script in `scripts/` can be used to regenerate this data with additional variance.

