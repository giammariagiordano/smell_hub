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
        self.developer_files: Dict[str, Set[str]] = {}
        self.file_developers: Dict[str, Set[str]] = {}

    def build_collaboration_network(self, commits: List[Commit]):
        """Builds both bipartite (Dev-File) and projected (Dev-Dev) collaboration networks."""
        self.bipartite_collaboration.clear()
        self.collaboration_graph.clear()
        self.developer_files = {}
        self.file_developers = {}

        for commit in commits:
            author_id = commit.author_id
            if not author_id:
                continue
            self.bipartite_collaboration.add_node(author_id, type='developer')
            self.collaboration_graph.add_node(author_id)
            author_files = self.developer_files.setdefault(author_id, set())
            for file_path in commit.files_modified:
                if not file_path:
                    continue
                self.bipartite_collaboration.add_node(file_path, type='file')
                self.bipartite_collaboration.add_edge(author_id, file_path)
                author_files.add(file_path)
                self.file_developers.setdefault(file_path, set()).add(author_id)

        edge_weights: Dict[Tuple[str, str], int] = {}
        for developers in self.file_developers.values():
            developer_list = sorted(dev for dev in developers if dev)
            if len(developer_list) < 2:
                continue
            for i, dev1 in enumerate(developer_list):
                for dev2 in developer_list[i + 1:]:
                    edge_key = (dev1, dev2)
                    edge_weights[edge_key] = int(edge_weights.get(edge_key, 0)) + 1

        for (dev1, dev2), weight in edge_weights.items():
            self.collaboration_graph.add_edge(dev1, dev2, weight=weight)

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
