from typing import List, Dict
import os
from models.schemas import Developer, Commit

class DeveloperClassifier:
    AI_EXTENSIONS = {'.ipynb', '.h5', '.onnx', '.pickle', '.pkl', '.model', '.pt', '.ckpt'}
    AI_KEYWORDS = {
        'tensorflow', 'keras', 'torch', 'pytorch', 'scikit', 'sklearn', 'xgboost', 'lightgbm',
        'pandas', 'numpy', 'jupyter', 'feature', 'dataset', 'preprocess', 'augmentation',
        'training', 'validation', 'evaluate', 'inference', 'model', 'hyperparameter',
        'neural', 'transformer', 'bert', 'gpt', 'llm', 'embedding', 'prediction'
    }
    
    SE_EXTENSIONS = {
        '.java', '.c', '.cpp', '.h', '.js', '.ts', '.css', '.html', '.sql',
        '.go', '.rs', '.yaml', '.yml', '.toml', '.ini', '.conf'
    }
    SE_KEYWORDS = {
        'api', 'service', 'controller', 'middleware', 'database', 'schema',
        'endpoint', 'request', 'response', 'auth', 'login', 'security',
        'deploy', 'docker', 'kubernetes', 'ci', 'cd', 'pipeline', 'logging',
        'monitoring', 'config', 'refactor', 'unittest', 'integration',
        'architecture', 'microservice', 'cloud', 'observability', 'bugfix'
    }

    HYBRID_KEYWORDS = {
        'mlflow', 'kubeflow', 'tfx', 'model serving', 'serving', 'airflow',
        'feature store', 'online inference', 'batch inference', 'model deploy',
        'model deployment', 'mle', 'mlops'
    }

    AI_PATH_HINTS = {
        'notebook', 'notebooks', 'dataset', 'data', 'feature', 'train', 'training',
        'model', 'inference', 'ml', 'ai'
    }
    SE_PATH_HINTS = {
        'api', 'service', 'backend', 'deploy', 'infra', 'k8s', 'docker',
        'controller', 'routes', 'auth', 'tests', 'monitoring', 'config'
    }

    def classify_developers(self, developers: List[Developer], commits: List[Commit]):
        dev_scores = {d.id: {'se': 0, 'ai': 0} for d in developers}
        
        for commit in commits:
            author_id = commit.author_id
            if author_id not in dev_scores: continue

            msg = commit.message.lower()
            ai_hits = sum(1 for kw in self.AI_KEYWORDS if kw in msg)
            se_hits = sum(1 for kw in self.SE_KEYWORDS if kw in msg)
            hybrid_hits = sum(1 for kw in self.HYBRID_KEYWORDS if kw in msg)
            dev_scores[author_id]['ai'] += ai_hits * 0.35
            dev_scores[author_id]['se'] += se_hits * 0.35
            if hybrid_hits:
                # Hybrid signals indicate end-to-end AI + software integration.
                dev_scores[author_id]['ai'] += hybrid_hits * 0.5
                dev_scores[author_id]['se'] += hybrid_hits * 0.5

            # Extension based scoring
            for file in commit.files_modified:
                file_l = file.lower()
                _, ext = os.path.splitext(file_l)
                if ext in self.AI_EXTENSIONS:
                    dev_scores[author_id]['ai'] += 1.8
                elif ext in self.SE_EXTENSIONS:
                    dev_scores[author_id]['se'] += 1.3
                elif ext == '.py':
                    # Python files can be either side: use path + message context.
                    dev_scores[author_id]['se'] += 0.35
                    dev_scores[author_id]['ai'] += 0.35

                if any(h in file_l for h in self.AI_PATH_HINTS):
                    dev_scores[author_id]['ai'] += 0.9
                if any(h in file_l for h in self.SE_PATH_HINTS):
                    dev_scores[author_id]['se'] += 0.9

                # Explicit hybrid tools in filenames/paths boost both sides.
                if any(h in file_l for h in ('mlflow', 'kubeflow', 'tfx', 'airflow')):
                    dev_scores[author_id]['ai'] += 0.7
                    dev_scores[author_id]['se'] += 0.7

        for dev in developers:
            scores = dev_scores[dev.id]
            total = scores['se'] + scores['ai']
            if total < 0.5:
                dev.classification = "Unknown"
                dev.se_score = 0.0
                dev.ai_score = 0.0
                dev.ml_score = 0.0
                continue
            
            se_ratio = scores['se'] / total
            ai_ratio = scores['ai'] / total
            
            dev.se_score = round(se_ratio * 10, 1)
            dev.ai_score = round(ai_ratio * 10, 1)
            dev.ml_score = dev.ai_score
            
            # Clear specialization
            if se_ratio >= 0.70 and ai_ratio < 0.30:
                dev.classification = "Software Engineer"
            elif ai_ratio >= 0.70 and se_ratio < 0.30:
                dev.classification = "AI-Engineer"
            # Balanced profile with meaningful evidence on both sides
            elif scores['se'] >= 2.0 and scores['ai'] >= 2.0:
                dev.classification = "Hybrid"
            else:
                dev.classification = "Software Engineer" if se_ratio > ai_ratio else "AI-Engineer"
