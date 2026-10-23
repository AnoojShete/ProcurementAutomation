# Future enhancements, references and conclusion

## Future enhancements

| Area | Enhancement |
|---|---|
| E-signature | Connect a legally recognised provider (DocuSign / Documenso clients exist but are off); a keyed seal instead of an unkeyed SHA-256 |
| Deployment | Kubernetes manifests, TLS between services, managed Kafka and Postgres |
| Documents | Better accuracy on poor scans (images read correctly ~50 % of the time; PDFs 100 %) |
| ERP | Push approved orders and matched invoices to an ERP (SAP, Tally) |
| Notifications | Teams / Slack channels besides email; real distribution lists for role mailboxes |
| Selective automation | Use the research study's calibrated gate in production so more invoices skip review at a guaranteed error rate |
| Vendors | A vendor portal: vendors submit quotes and see order status |

## References

- FastAPI — <https://fastapi.tiangolo.com>
- Temporal — <https://docs.temporal.io>
- Redpanda (Kafka API) — <https://docs.redpanda.com>
- Docling — <https://github.com/DS4SD/docling>; PaddleOCR — <https://github.com/PaddlePaddle/PaddleOCR>
- LayoutLMv3 — Huang et al., 2022, *LayoutLMv3: Pre-training for Document AI with Unified Text and Image Masking*
- CUAD — Hendrycks et al., 2021, *CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review*; model `alex-apostolo/legal-bert-base-cuad`
- IsolationForest — Liu, Ting and Zhou, 2008; SHAP — Lundberg and Lee, 2017
- OpenSanctions consolidated list — <https://www.opensanctions.org> (CC BY-NC 4.0)
- MkDocs Material — <https://squidfunk.github.io/mkdocs-material>

## Conclusion

The platform takes a document from arrival to a signed contract and a
matched invoice with no manual hand-offs, while keeping people in charge of
the decisions that matter: approvals, signatures and anything the system is
unsure about. Failures are visible (the Failed folder, failed events, the
validation result of every stage), every step is audited, and an
administrator runs it from one Control Panel. It is a working, tested
prototype (1,276 automated service tests, end-to-end suites through the
gateway) that runs on one machine with Docker Compose.
