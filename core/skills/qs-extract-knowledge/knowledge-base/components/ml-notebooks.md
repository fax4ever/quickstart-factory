---
name: ml-notebooks
description: "Jupyter notebooks implementing train-save-deploy-cleanup ML lifecycle with sklearn KNN, MinIO, and KServe on RHOAI"
summary: "Implements a complete train-save-deploy-cleanup ML lifecycle as a sequential four-notebook Jupyter pipeline on RHOAI, training a KNN collaborative filtering model (cosine similarity on transaction behavioral features via pandas groupby aggregation) and deploying it as a KServe InferenceService with programmatic Kubernetes Python client calls. Use when ML model training and serving should be driven interactively from RHOAI workbench notebooks rather than Helm charts or KFP pipelines -- the single approach wraps a custom KNNRecommender(BaseEstimator) in an sklearn Pipeline with StandardScaler for MLServer SKLearnModel compatibility and deploys ServingRuntime + InferenceService (RawDeployment mode) with create-or-update (409 Conflict patch) semantics via Jinja2-style YAML template substitution. Three artifacts upload to MinIO via boto3: pipeline.pkl, the custom knn_recommender.py module, and model-settings.json (`implementation: mlserver_sklearn.SKLearnModel`, `uri: /mnt/models/pipeline.pkl`); inter-notebook parameters pass through vars.txt; serving uses `quay.io/rh-ai-quickstart/mlserver-sklearn:1.7.0`; cleanup deletes resources in reverse dependency order (InferenceService, ServingRuntime, MinIO, Secrets, RBAC). Custom Python module must be uploaded alongside the pickle and ServingRuntime must set PYTHONPATH=/mnt/models for MLServer deserialization, model-settings.json URI must match the KServe storage mount path, MinIO credentials are hardcoded in YAML templates (minio/minio123), deployment templates must be in notebook CWD, and RBAC cleanup may require cluster-admin privileges."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, scikit-learn, pandas, numpy, boto3, pickle, kubernetes-client, mlserver]
  ai_pattern: [data-pipeline, model-serving, embeddings]
  platform: [rhoai, openshift, kserve, mlserver]
  data_layer: [minio]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Four-notebook ML pipeline: train KNN alert recommender, save sklearn Pipeline to MinIO, deploy as KServe InferenceService via MLServer, cleanup resources"
    approach: "A"
---

# ML Notebooks

## Overview

Jupyter notebooks that implement a complete ML lifecycle as a sequential four-notebook pipeline: train a model, save it to S3-compatible storage (MinIO), deploy it as a KServe InferenceService on OpenShift AI, and clean up all deployed resources. In the spending-transaction-monitor quickstart, these notebooks train a KNN-based collaborative filtering model for transaction alert recommendations, wrap it in an sklearn Pipeline for MLServer compatibility, and deploy it using the Kubernetes Python client to programmatically create ServingRuntime and InferenceService custom resources.

## Tech Stack & Dependencies

- **Runtime:** Python (RHOAI workbench image)
- **Container image:** Standard RHOAI workbench image (no custom Dockerfile for the notebooks themselves); model served by `quay.io/rh-ai-quickstart/mlserver-sklearn:1.7.0`
- **Key dependencies:**
  - `pandas`, `numpy` -- data loading and feature engineering
  - `scikit-learn` (`NearestNeighbors`, `StandardScaler`, `Pipeline`) -- model training and packaging
  - `boto3`, `botocore` -- S3-compatible MinIO access for data retrieval and model upload
  - `pickle` -- model serialization
  - `kubernetes` (`client`, `config`) -- programmatic deployment of K8s/KServe resources
  - `pyyaml` -- YAML template loading for deployment manifests
- **Helm subchart:** None (notebooks are run manually in an RHOAI workbench; deployment uses YAML templates applied via the Kubernetes Python client)

## Key Patterns

### KNN Collaborative Filtering for Alert Recommendations

The training notebook (`1_train_alert_model.ipynb`) builds behavioral features from transaction history (amount statistics, merchant diversity, credit utilization) and trains a KNN model using cosine similarity. Alert labels are either loaded from real user preferences or generated via heuristic rules (top-25% quantile thresholds).

```python
knn_model = NearestNeighbors(
    n_neighbors=min(N_NEIGHBORS, len(X_scaled)),
    metric=METRIC,
    algorithm='brute'
)
knn_model.fit(X_scaled)
```

Feature columns are aggregated per user from transaction data using pandas groupby:

```python
tx_agg = transactions_df.groupby('user_id').agg({
    'amount': ['count', 'mean', 'std', 'max', 'sum'],
    'merchant_name': pd.Series.nunique,
    'merchant_category': pd.Series.nunique
})
```

### Custom Estimator Wrapped in sklearn Pipeline for MLServer

The save notebook (`2_save_model.ipynb`) creates a `KNNRecommender` class extending `sklearn.base.BaseEstimator` with a `predict()` method, then wraps it in an `sklearn.pipeline.Pipeline` alongside a `StandardScaler`. This pattern is required for MLServer's `mlserver_sklearn.SKLearnModel` implementation, which expects a pickled sklearn object with a `predict()` interface.

```python
class KNNRecommender(BaseEstimator):
    def __init__(self, knn_model, alert_labels, alert_types, threshold=0.4):
        self.knn_model = knn_model
        self.alert_labels = alert_labels
        self.alert_types = alert_types
        self.threshold = threshold
    
    def predict(self, X):
        k_neighbors = min(5, len(self.alert_labels))
        distances, indices = self.knn_model.kneighbors(X, n_neighbors=k_neighbors)
        all_recommendations = []
        for idx_list in indices:
            similar_labels = self.alert_labels[idx_list]
            probabilities = similar_labels.mean(axis=0)
            recommendations = [...]
            all_recommendations.append(recommendations)
        return np.array(all_recommendations, dtype=object)
```

The pipeline bundles scaler and recommender into a single serializable artifact:

```python
pipeline = Pipeline([
    ('scaler', model_artifacts['scaler']),
    ('recommender', knn_recommender)
])
```

### Model Artifacts Upload to MinIO with model-settings.json

The save notebook uploads three artifacts to MinIO: `pipeline.pkl` (the sklearn Pipeline), `knn_recommender.py` (the custom module so MLServer can import the class during deserialization), and `model-settings.json` (MLServer configuration).

```python
model_settings = {
    "name": model_name,
    "implementation": "mlserver_sklearn.SKLearnModel",
    "parameters": {
        "uri": "/mnt/models/pipeline.pkl"
    }
}
```

The `PYTHONPATH` in the ServingRuntime is set to include `/mnt/models` so MLServer can import the `knn_recommender` module when unpickling the Pipeline.

### Inter-Notebook Parameter Passing via vars.txt

The save notebook generates a `vars.txt` file containing deployment parameters (model version, name, S3 path) that the deploy notebook reads. This avoids hardcoding values across notebooks.

```python
# Notebook 2 writes:
with open("vars.txt", "w") as f:
    f.write(f'model_version={model_version}\n')
    f.write(f'model_name={model_name}\n')
    f.write(f's3_bucket={BUCKET_NAME}\n')
    f.write(f's3_model_path={s3_model_path}\n')

# Notebook 3 reads:
with open(vars_path, 'r') as f:
    for line in f:
        if '=' in line:
            key, value = line.strip().split('=', 1)
            deployment_vars[key] = value
            os.environ[key] = value
```

### Programmatic KServe Deployment via Kubernetes Python Client

The deploy notebook (`3_deploy_model.ipynb`) uses the Kubernetes Python client to create ServingRuntime (v1alpha1) and InferenceService (v1beta1) custom resources programmatically, with create-or-update semantics (catch 409 Conflict and patch).

```python
try:
    custom_api.create_namespaced_custom_object(
        group='serving.kserve.io',
        version='v1beta1',
        namespace=NAMESPACE,
        plural='inferenceservices',
        body=inference_service
    )
except ApiException as e:
    if e.status == 409:
        custom_api.patch_namespaced_custom_object(
            group='serving.kserve.io',
            version='v1beta1',
            namespace=NAMESPACE,
            plural='inferenceservices',
            name=inference_service['metadata']['name'],
            body=inference_service
        )
```

### Jinja2-Style YAML Template Substitution

The deploy notebook loads deployment YAML files containing `{{ variable }}` placeholders and substitutes them using regex before parsing.

```python
def substitute_template_vars(yaml_content, variables):
    for key, value in variables.items():
        pattern = r'\{\{\s*' + re.escape(key) + r'\s*\}\}'
        yaml_content = re.sub(pattern, str(value), yaml_content)
    return yaml_content
```

### KServe InferenceService with RawDeployment Mode

The InferenceService uses `serving.kserve.io/deploymentMode: RawDeployment` annotation, which deploys the model server as a standard Kubernetes Deployment rather than a Knative Service. The model is loaded from MinIO via the `storage` spec.

```yaml
annotations:
  serving.kserve.io/deploymentMode: RawDeployment
  openshift.io/display-name: "Alert Recommendation Model"
labels:
  opendatahub.io/dashboard: "true"
spec:
  predictor:
    model:
      modelFormat:
        name: sklearn
        version: "1"
      runtime: mlserver-sklearn
      storage:
        key: minio-secret
        path: {{ model_path }}
        parameters:
          endpoint: http://minio-service.{{ namespace }}.svc.cluster.local:9000
```

### Complete Resource Cleanup Notebook

The cleanup notebook (`4_cleanup_deployment.ipynb`) systematically deletes all ML pipeline resources in reverse dependency order: InferenceService, ServingRuntime, MinIO (Deployment, Services, PVC), Secrets, RBAC (Role, RoleBinding), and optionally the ServiceAccount. Each deletion is wrapped in try/except with 404 handling for idempotency.

## Configuration

- **Environment variables (training/save):**
  - `NAMESPACE` -- OpenShift namespace (default: `spending-transaction-monitor`)
  - `BUCKET_NAME` -- MinIO bucket for models (default: `models`)
  - `DATA_VERSION` -- data version prefix in MinIO (default: `1`)
  - `MODEL_VERSION` -- model version string (default: `1.0.0`)
  - `N_NEIGHBORS` -- KNN neighbor count (default: `5`)
  - `METRIC` -- KNN distance metric (default: `cosine`)
  - `MINIO_ENDPOINT` -- MinIO API endpoint URL
  - `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` -- MinIO credentials
- **Environment variables (deploy):**
  - `MODEL_NAME` -- deployed model name (default: `alert-recommender`)
  - `MODEL_PATH` -- S3 path within bucket (read from vars.txt)
- **Config files:** Deployment YAML templates in `ml-pipeline/deployment/` (minio.yaml, serving-runtime.yaml, inference-service.yaml, storage-config.yaml.template, rbac.yaml)
- **Helm values:** Not applicable (deployment uses YAML templates with sed/regex substitution, not Helm)

## Known Gotchas

- **Custom module must be uploaded alongside the pickle:** The `KNNRecommender` class is defined in a separate `knn_recommender.py` module that is uploaded to MinIO alongside `pipeline.pkl`. The ServingRuntime sets `PYTHONPATH` to include `/mnt/models` so MLServer can import the module during deserialization. Without this, unpickling fails with `ModuleNotFoundError`.
- **MinIO data fallback to local files:** The training notebook attempts to load data from MinIO first and falls back to local `./data/` CSV files if MinIO is unavailable. This dual-path makes the notebook work both in-cluster and during local development, but the local path (`./data/users.csv`) is relative and assumes the notebook CWD contains the data directory.
- **model-settings.json `uri` must match the KServe storage mount path:** The `model-settings.json` sets `"uri": "/mnt/models/pipeline.pkl"` which is where KServe mounts model artifacts from S3. If the S3 prefix structure changes, both the S3 upload path and this URI must be updated in sync.
- **Deployment notebook references `./storage-config.yaml.template` from CWD:** The deploy notebook calls `load_and_substitute_yaml('./storage-config.yaml.template', variables)` assuming the notebook is run from a directory containing this template. However, the template lives in `ml-pipeline/deployment/`, so the notebook must be executed with the correct working directory or the path adjusted.
- **MinIO credentials stored in YAML templates:** The `minio.yaml` template contains hardcoded credentials in the Secret (`minio` / `minio123`). The `storage-config.yaml.template` also contains `"access_key_id": "minio"` and `"secret_access_key": "minio123"` in plaintext stringData.
- **RBAC deletion may require elevated privileges:** The cleanup notebook warns that deleting Roles and RoleBindings requires cluster-admin or namespace-admin permissions that the notebook ServiceAccount may not have, providing manual `oc delete` fallback commands.

## Testing Notes

- Run notebooks in strict order: 1 (train) -> 2 (save to MinIO) -> 3 (deploy to OpenShift) -> 4 (cleanup)
- Notebook 1 can run locally without MinIO (uses local data fallback), but notebook 2 requires a reachable MinIO endpoint
- Notebook 3 requires either in-cluster config (`load_incluster_config()`) when running in an RHOAI workbench, or local kubeconfig when running externally
- After notebook 3 completes, verify the InferenceService is ready: `oc get isvc alert-recommender -n spending-transaction-monitor`
- Test the model endpoint via curl: `curl http://alert-recommender-predictor.<namespace>.svc.cluster.local:8080/v2/health/ready`
- The deploy script (`ml-pipeline/deployment/deploy.sh`) provides an alternative non-notebook deployment path using `oc apply` with sed-based variable substitution

## Related Patterns

- See `minio.md` for S3-compatible storage patterns used as the model artifact store
- See `model-serving.md` for other KServe InferenceService deployment patterns
- See `notebooks.md` for other notebook patterns (data prep, KFP pipelines, interactive demos)
