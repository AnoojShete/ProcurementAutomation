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
- `services/document-vendor-agent/scripts/generate_classification_dataset.py` regenerates it.

## Is it used?

Yes, since 16 Oct 2026 (FR-29) — as part of the training data. The
classifier is trained at image build by
`services/document-vendor-agent/ml/train_classifier.py` on these 105 rows
**plus** a harder generated corpus (`ml/classification_corpus.py`: invoices,
POs and quotes with OCR noise or no title, and *other* paperwork such as
delivery notes, statements and credit notes). On their own these rows are
too easy — every one carries its title, so any classifier scores ~100 %.
The model is kept only if it beats the keyword classifier on held-out
documents; results in `docs/results/classifier.md`.
