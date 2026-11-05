# Error Analysis - Held-out Split

Generated from the actual held-out rankings and labels; no case is hand-invented. The labels are single-annotator synthetic judgements, so every finding is scoped to this corpus.

## Summary

| Outcome | Count |
| --- | --- |
| partial match in top k | 11 |
| strong match in top k | 8 |
| strong match to not relevant job | 5 |

Top-k cutoff: 10.

## Cases

### 1. r11 -> j08 (Junior Machine Learning Engineer)

- Kind: `partial_match_in_top_k`; rank 2; score 0.661; label 1.
- Missing required: none.
- Missing preferred: Natural Language Processing, SQL, Pandas.
- Experience: partial_match (Evidence indicates 7.2 years vs a stated maximum of 2; the posting may target a different seniority level.).
- Evidence shown: ML: PyTorch, Deep Learning, Computer Vision, Convolutional Neural Networks, TensorFlow, Model Evaluation, Transfer Learning

### 2. r11 -> j01 (Machine Learning Engineer, NLP)

- Kind: `partial_match_in_top_k`; rank 3; score 0.535; label 1.
- Missing required: Natural Language Processing, Transformers, BERT.
- Missing preferred: MLflow, FAISS, Information Retrieval.
- Experience: clear_match (Evidence indicates 7.2 years against a stated requirement of 3-6 years.).
- Evidence shown: Machine Learning Engineer | SensorWorks | 2019-10 - 2021-04

### 3. r11 -> j07 (DevOps Engineer)

- Kind: `strong_match_to_not_relevant_job`; rank 6; score 0.472; label 0.
- Missing required: Terraform, CI/CD.
- Missing preferred: Prometheus, Grafana, Linux.
- Experience: clear_match (Evidence indicates 7.2 years against a stated requirement of 5+ years.).
- Evidence shown: Engineering: Docker, AWS, Model Deployment, Git

### 4. r11 -> j03 (Backend Engineer (Python))

- Kind: `strong_match_to_not_relevant_job`; rank 8; score 0.433; label 0.
- Missing required: FastAPI, PostgreSQL, REST APIs.
- Missing preferred: Redis, Celery.
- Experience: clear_match (Evidence indicates 7.2 years against a stated requirement of 4+ years.).
- Evidence shown: Deployed models as Docker services on AWS with batch and real-time inference.

### 5. r11 -> j15 (AI Engineer, LLM Applications)

- Kind: `strong_match_to_not_relevant_job`; rank 10; score 0.406; label 0.
- Missing required: Large Language Models, Retrieval-Augmented Generation, Transformers, Semantic Search.
- Missing preferred: FAISS, FastAPI.
- Experience: clear_match (Evidence indicates 7.2 years against a stated requirement of 3-6 years.).
- Evidence shown: Deployed models as Docker services on AWS with batch and real-time inference.

### 6. r12 -> j03 (Backend Engineer (Python))

- Kind: `partial_match_in_top_k`; rank 5; score 0.541; label 1.
- Missing required: FastAPI, PostgreSQL, REST APIs.
- Missing preferred: Redis, Celery.
- Experience: clear_match (Evidence indicates 7.9 years against a stated requirement of 4+ years.).
- Evidence shown: MLOps Engineer | Falcon Data Platform | 2021-09 - present

### 7. r12 -> j05 (Data Engineer)

- Kind: `partial_match_in_top_k`; rank 6; score 0.525; label 1.
- Missing required: Apache Airflow, Apache Spark, Snowflake.
- Missing preferred: Apache Kafka, dbt, Data Quality.
- Experience: clear_match (Evidence indicates 7.9 years against a stated requirement of 4-7 years.).
- Evidence shown: Ran a Kubeflow-based model platform supporting 30 data scientists.

### 8. r12 -> j20 (Data Science Manager)

- Kind: `strong_match_to_not_relevant_job`; rank 9; score 0.487; label 0.
- Missing required: Leadership, Stakeholder Management, Mentoring.
- Missing preferred: A/B Testing, Statistics, Communication.
- Experience: clear_match (Evidence indicates 7.9 years against a stated requirement of 6-12 years.).
- Evidence shown: MLOps engineer with 6 years of experience running model platforms, CI/CD and monitoring for data science teams.

### 9. r13 -> j09 (Business Intelligence Analyst)

- Kind: `partial_match_in_top_k`; rank 4; score 0.708; label 1.
- Missing required: none.
- Missing preferred: Business Intelligence.
- Experience: clear_match (Evidence indicates 3.6 years against a stated requirement of 3-5 years.).
- Evidence shown: Analytics: SQL, Microsoft Excel, Data Analysis, Tableau, Statistics

### 10. r13 -> j18 (Healthcare Data Analyst)

- Kind: `partial_match_in_top_k`; rank 5; score 0.692; label 1.
- Missing required: Healthcare Analytics.
- Missing preferred: Data Quality.
- Experience: clear_match (Evidence indicates 3.6 years against a stated requirement of 3-6 years.).
- Evidence shown: Analytics: SQL, Microsoft Excel, Data Analysis, Tableau, Statistics

### 11. r13 -> j22 (Product Analyst)

- Kind: `partial_match_in_top_k`; rank 6; score 0.637; label 1.
- Missing required: Metrics Design, A/B Testing.
- Missing preferred: Product Management.
- Experience: clear_match (Evidence indicates 3.6 years against a stated requirement of 2-5 years.).
- Evidence shown: Analytics: SQL, Microsoft Excel, Data Analysis, Tableau, Statistics

### 12. r13 -> j14 (Senior Data Scientist)

- Kind: `strong_match_to_not_relevant_job`; rank 7; score 0.599; label 0.
- Missing required: Machine Learning, A/B Testing.
- Missing preferred: XGBoost, Mentoring.
- Experience: below_requirement (Evidence indicates 3.6 years vs a stated minimum of 5; tenure is derived only from dated roles in the experience section.).
- Evidence shown: Built a cohort analysis and segmentation study for a fictional subscription business.

## Interpretation

- Labels are single-annotator judgements on a synthetic corpus.
- A relevance-0 item in the top-k is a ranking error measured against those labels, not proof that the job is objectively unsuitable.
- Missing requirements mean they were not evidenced in the resume text.
