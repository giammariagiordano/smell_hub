import ast
from typing import List, Dict, Any
from models.schemas import ProjectMetrics

class QualityMetricsAnalyzer:
    def analyze_file(self, file_path: str, source_code: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(source_code)
        except:
            return {}

        metrics = {
            'loc': len(source_code.splitlines()),
            'nom': 0,
            'wmc': 0,
            'cbo': 0,
            'rfc': 0,
            'lcom': 0,
            'dit': 0,
            'noc': 0
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                metrics['nom'] += 1
                # Simplified WMC using cyclomatic complexity (roughly)
                complexity = 1
                for subnode in ast.walk(node):
                    if isinstance(subnode, (ast.If, ast.For, ast.While, ast.And, ast.Or)):
                        complexity += 1
                metrics['wmc'] += complexity
                
            if isinstance(node, ast.ClassDef):
                metrics['noc'] = len(node.bases) # Simplified NOC as number of base classes
                metrics['dit'] = 1 # Simplified DIT
                # Count methods in class
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        metrics['rfc'] += 1
                
            if isinstance(node, ast.Call):
                metrics['rfc'] += 1 # RFC includes external calls
                if isinstance(node.func, ast.Attribute):
                    metrics['cbo'] += 1 # Simplified CBO for external class interaction
                
        return metrics

    def compute_project_aggregates(self, file_metrics: List[Dict[str, Any]]) -> ProjectMetrics:
        # Aggregation logic
        agg = ProjectMetrics(project_id="current")
        for m in file_metrics:
            agg.loc += m.get('loc', 0)
            agg.nom += m.get('nom', 0)
            agg.wmc += m.get('wmc', 0)
        return agg
