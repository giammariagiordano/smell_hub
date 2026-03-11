import networkx as nx
from typing import List, Dict, Set, Tuple
from datetime import datetime
from models.schemas import Commit, Developer

class NetworkBuilder:
    def __init__(self):
        self.collaboration_graph = nx.Graph()  # Dev-Dev
        self.communication_graph = nx.Graph()  # Dev-Dev
        self.dependency_graph = nx.DiGraph()  # File-File
        self.bipartite_collaboration = nx.Graph() # Dev-File
        self.communication_source = "none"

    def build_collaboration_network(self, commits: List[Commit]):
        """Builds both bipartite (Dev-File) and projected (Dev-Dev) collaboration networks."""
        self.bipartite_collaboration.clear()
        self.collaboration_graph.clear()
        
        for commit in commits:
            author_id = commit.author_id
            self.bipartite_collaboration.add_node(author_id, type='developer')
            for file_path in commit.files_modified:
                self.bipartite_collaboration.add_node(file_path, type='file')
                self.bipartite_collaboration.add_edge(author_id, file_path)
        
        # Project to Dev-Dev
        developers = [n for n, d in self.bipartite_collaboration.nodes(data=True) if d.get('type') == 'developer']
        # Two developers collaborate if they modify the same file
        for i, dev1 in enumerate(developers):
            for dev2 in developers[i+1:]:
                # Check for common neighbors (files)
                common_files = set(self.bipartite_collaboration.neighbors(dev1)) & set(self.bipartite_collaboration.neighbors(dev2))
                if common_files:
                    if self.collaboration_graph.has_edge(dev1, dev2):
                        self.collaboration_graph[dev1][dev2]['weight'] += len(common_files)
                    else:
                        self.collaboration_graph.add_edge(dev1, dev2, weight=len(common_files))

    def build_communication_network(self, interactions: List[Tuple[str, str, datetime]]):
        """Builds communication network from (sender_id, receiver_id, timestamp) tuples."""
        self.communication_graph.clear()
        for sender, receiver, _ in interactions:
            if self.communication_graph.has_edge(sender, receiver):
                self.communication_graph[sender][receiver]['weight'] += 1
            else:
                self.communication_graph.add_edge(sender, receiver, weight=1)

    def build_dependency_network_historical(self, commits: List[Commit]):
        """Builds historical dependency (co-change) network."""
        self.dependency_graph.clear()
        for commit in commits:
            files = commit.files_modified
            for i, f1 in enumerate(files):
                for f2 in files[i+1:]:
                    if self.dependency_graph.has_edge(f1, f2):
                        self.dependency_graph[f1][f2]['weight'] += 1
                        self.dependency_graph[f2][f1]['weight'] += 1
                    else:
                        self.dependency_graph.add_edge(f1, f2, weight=1)
                        self.dependency_graph.add_edge(f2, f1, weight=1)

    def get_transitive_closure_communication(self) -> nx.Graph:
        """Computes the transitive closure of the communication graph."""
        return nx.transitive_closure(self.communication_graph.to_directed()).to_undirected()
