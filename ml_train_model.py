import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
import joblib

# Load student data CSV exported from your database or student_list_sample.csv
csv_file = 'student_list_sample.csv'  # Make sure this file is in backend folder

# Load dataset
df = pd.read_csv(csv_file)

# Example data preprocessing:
# You need columns representing relevant features:
# For demo, assume CSV has enrollment_no, attendance_rate, assignment_avg, exam_score etc.
# Adapt below according to your real data fields.

# Add or simulate these columns if missing (example synthetic data):
if 'attendance_rate' not in df.columns:
    import numpy as np
    np.random.seed(42)
    df['attendance_rate'] = np.random.uniform(0.4, 1.0, size=len(df))
if 'assignment_avg' not in df.columns:
    df['assignment_avg'] = np.random.uniform(40, 95, size=len(df))
if 'exam_score' not in df.columns:
    df['exam_score'] = np.random.uniform(40, 100, size=len(df))
if 'gender' not in df.columns:
    # For demo only: randomly assign gender: 1 male, 0 female
    df['gender'] = np.random.randint(0, 2, size=len(df))
if 'age' not in df.columns:
    df['age'] = np.random.randint(18, 25, size=len(df))

# Define binary target 'at_risk' based on attendance_rate and assignment_avg thresholds
df['at_risk'] = ((df['attendance_rate'] < 0.7) | (df['assignment_avg'] < 65)).astype(int)

# Features and target
features = ['age', 'gender', 'attendance_rate', 'assignment_avg', 'exam_score']
X = df[features]
y = df['at_risk']

# Split data into train and test sets (70% train, 30% test)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

# Train Random Forest classifier
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Predict on test set
y_pred = model.predict(X_test)

# Evaluate performance
print(f"Accuracy: {accuracy_score(y_test, y_pred):.2f}")
print("Classification Report:")
print(classification_report(y_test, y_pred, zero_division=0))

# Save the trained model to a file for later use in backend APIs
model_filename = 'attendance_risk_model.joblib'
joblib.dump(model, model_filename)
print(f"Model saved to {model_filename}")
