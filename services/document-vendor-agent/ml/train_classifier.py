import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, classification_report
import datetime

def main():
    data_path = r"d:\ProcurementAutomation\data\synthetic-classification\classification_training_data.csv"
    artifacts_dir = r"d:\ProcurementAutomation\services\document-vendor-agent\ml\artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)
    
    # Load dataset
    print(f"Loading data from {data_path}")
    df = pd.read_csv(data_path)
    
    X = df['text']
    y = df['label']
    
    # 70 / 15 / 15 split
    # First split into 70% train and 30% temp
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, random_state=42)
    # Then split temp into 15% val and 15% test
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42)
    
    print(f"Train size: {len(X_train)}, Val size: {len(X_val)}, Test size: {len(X_test)}")
    
    # Pipeline
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(lowercase=True, stop_words='english')),
        ('clf', LogisticRegression(random_state=42))
    ])
    
    print("Training model...")
    pipeline.fit(X_train, y_train)
    
    # Evaluate
    val_preds = pipeline.predict(X_val)
    val_acc = accuracy_score(y_val, val_preds)
    print(f"Validation Accuracy: {val_acc:.4f}")
    
    test_preds = pipeline.predict(X_test)
    test_acc = accuracy_score(y_test, test_preds)
    print(f"Test Accuracy: {test_acc:.4f}")
    print("Classification Report (Test):")
    print(classification_report(y_test, test_preds))
    
    # Optional: Log to MLflow if mlflow is available
    try:
        import mlflow
        import mlflow.sklearn
        mlflow.set_experiment("document_classification")
        with mlflow.start_run():
            mlflow.log_param("model_type", "Tfidf_LogisticRegression")
            mlflow.log_metric("val_accuracy", val_acc)
            mlflow.log_metric("test_accuracy", test_acc)
            mlflow.sklearn.log_model(pipeline, "model")
            print("Logged to MLflow successfully.")
    except ImportError:
        print("MLflow not installed, skipping MLflow logging.")
    except Exception as e:
        print(f"MLflow logging failed: {e}")
        
    # Save artifacts
    model_path = os.path.join(artifacts_dir, "classifier.joblib")
    version_path = os.path.join(artifacts_dir, "classifier_version.txt")
    
    joblib.dump(pipeline, model_path)
    
    version_info = f"Model trained on: {datetime.datetime.now().isoformat()}\nValidation Accuracy: {val_acc:.4f}\nTest Accuracy: {test_acc:.4f}"
    with open(version_path, "w", encoding="utf-8") as f:
        f.write(version_info)
        
    print(f"Saved model to {model_path}")
    print(f"Saved version info to {version_path}")

if __name__ == "__main__":
    main()
