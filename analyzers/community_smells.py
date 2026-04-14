import networkx as nx
from typing import List, Tuple, Dict, Optional
from models.schemas import SmellInstance
from core.network_builder import NetworkBuilder


class CommunitySmellAnalyzer:
    def __init__(self, network_builder: NetworkBuilder):
        self.nb = network_builder

    # ─────────────────────────────────────────────── helpers ────────────────
    def _dev_nodes(self):
        return [
            n for n, d in self.nb.bipartite_collaboration.nodes(data=True)
            if d.get("type") == "developer"
        ]

    def _communities(self, G: nx.Graph):
        if G.number_of_nodes() < 2:
            return []
        try:
            return list(nx.community.greedy_modularity_communities(G))
        except Exception:
            return []

    # ─────────────────────────────── Organisational Silo ────────────────────
    def detect_organisational_silo(self) -> List[SmellInstance]:
        """
        Two developers share a file (co-commit) but belong to different
        connected components when the *communication* graph is the basis.
        When we have no communication data we fall back to a 'weak silo':
        developers who never co-edit any file yet both appear in the repo.
        """
        smells = []
        comm = self.nb.communication_graph

        if comm.number_of_nodes() > 0:
            # Real communication data available → classic definition
            em_star = nx.transitive_closure(comm.to_directed()).to_undirected()
            for u, v in self.nb.collaboration_graph.edges():
                if not em_star.has_edge(u, v):
                    shared_files = []
                    try:
                        shared_files = sorted(
                            list(set(self.nb.developer_files.get(u, set())) & set(self.nb.developer_files.get(v, set())))
                        )
                    except Exception:
                        shared_files = []

                    smells.append(SmellInstance(
                        smell_id="organisational_silo",
                        name="Organisational Silo",
                        type="Community",
                        description=f"{u} and {v} collaborate but do not communicate.",
                        affected_entities=[u, v],
                        message=f"Silo: code coupling without communication between {u} and {v}.",
                        evidence={
                            "mode": "pair_no_communication_path",
                            "communication_source": getattr(self.nb, "communication_source", "unknown"),
                            "pair": [u, v],
                            "collaboration_weight": int(self.nb.collaboration_graph.get_edge_data(u, v, {}).get("weight", 1)),
                            "shared_files_count": len(shared_files),
                            "shared_files_sample": shared_files[:8],
                            "communication_path_exists": False,
                        }
                    ))
        else:
            # Fallback: without communication data, an organisational silo consists of 
            # isolated sub-communities (disconnected components) of size >= 2.
            # They collaborate internally, but are completely cut off from the rest of the project.
            components = list(nx.connected_components(self.nb.collaboration_graph))
            if len(components) > 1: # If there are multiple disconnected parts
                for comp in components:
                    if len(comp) >= 2: # Ignore Lone Wolves (size 1)
                        nodes = list(comp)
                        smells.append(SmellInstance(
                            smell_id="organisational_silo",
                            name="Organisational Silo",
                            type="Community",
                            description=f"Isolated sub-community of {len(nodes)} developers with no external collaboration.",
                            affected_entities=nodes,
                            message=f"Silo: Isolated collaborative group of {len(nodes)}.",
                            evidence={
                                "mode": "isolated_collaboration_component",
                                "communication_source": getattr(self.nb, "communication_source", "unknown"),
                                "component_size": len(nodes),
                                "component_nodes": nodes,
                                "communication_path_exists": False,
                            }
                        ))
        return smells

    # ───────────────────────────────── Lone Wolf ─────────────────────────────
    def detect_lone_wolf(self) -> List[SmellInstance]:
        """
        A developer who modifies files but NEVER co-edits any file with
        another developer (zero degree in the collaboration graph).
        """
        smells = []
        all_devs = set(self._dev_nodes())
        collab_devs = set(self.nb.collaboration_graph.nodes())

        # Devs present in the bipartite graph but with no collaboration edges
        for dev in all_devs:
            degree = self.nb.collaboration_graph.degree(dev) if dev in collab_devs else 0
            if degree == 0:
                smells.append(SmellInstance(
                    smell_id="lone_wolf",
                    name="Lone Wolf",
                    type="Community",
                    description=f"{dev} contributes to the repo but never co-edits files with others.",
                    affected_entities=[dev],
                    message=f"Lone wolf: {dev} works in complete isolation."
                ))
        return smells

    # ───────────────────────────────── Bottleneck ────────────────────────────
    def detect_bottleneck(self) -> List[SmellInstance]:
        """
        Developers with high betweenness centrality in the collaboration graph:
        they are the sole communication bridges across sub-communities.
        Threshold: centrality >= 0.25 (sits on ≥25% of shortest paths).
        """
        smells = []
        G = self.nb.collaboration_graph
        if G.number_of_nodes() < 3:
            return []

        try:
            bc = nx.betweenness_centrality(G, normalized=True)
        except Exception:
            return []

        threshold = 0.25
        for node, score in bc.items():
            if score >= threshold:
                smells.append(SmellInstance(
                    smell_id="bottleneck",
                    name="Bottleneck",
                    type="Community",
                    description=(
                        f"{node} is a collaboration bottleneck "
                        f"(centrality={score:.2f})."
                    ),
                    affected_entities=[node],
                    message=(
                        f"Bottleneck: {node} sits on {score*100:.0f}% "
                        "of collaboration shortest paths."
                    )
                ))
        return smells

    # ────────────────────────────── Black Cloud ──────────────────────────────
    def detect_black_cloud(self) -> List[SmellInstance]:
        """
        Two developer sub-communities are connected only through a single
        developer pair (single inter-community edge in collaboration graph).
        """
        smells = []
        G = self.nb.collaboration_graph
        communities = self._communities(G)
        if len(communities) < 2:
            return []

        node_to_comm: Dict[str, int] = {
            n: i for i, c in enumerate(communities) for n in c
        }

        comm_pairs: Dict[Tuple[int, int], List[Tuple[str, str]]] = {}
        for u, v in G.edges():
            cu, cv = node_to_comm.get(u), node_to_comm.get(v)
            if cu is None or cv is None or cu == cv:
                continue
            key = (min(cu, cv), max(cu, cv))
            comm_pairs.setdefault(key, []).append((u, v))

        for (c1, c2), edges in comm_pairs.items():
            if len(edges) == 1:
                u, v = edges[0]
                smells.append(SmellInstance(
                    smell_id="black_cloud",
                    name="Black Cloud",
                    type="Community",
                    description=(
                        f"Communities {c1} and {c2} interact only through {u} ↔ {v}."
                    ),
                    affected_entities=[u, v],
                    message=f"Black cloud: information bottleneck between communities {c1} and {c2}."
                ))
        return smells

    # ─────────────────────────────── Radio Silence ───────────────────────────
    def detect_radio_silence(self) -> List[SmellInstance]:
        """
        A developer has many collaboration edges (degree ≥ 3) but is
        completely absent from the communication graph.
        To reduce false positives, this smell is computed only when the
        communication graph has minimum coverage over collaborating developers.
        """
        smells = []
        collab_nodes = set(self.nb.collaboration_graph.nodes())
        if not collab_nodes:
            return []

        comm_nodes = set(self.nb.communication_graph.nodes())
        comm_edges = self.nb.communication_graph.number_of_edges()
        covered_nodes = len(collab_nodes & comm_nodes)
        coverage_ratio = covered_nodes / max(len(collab_nodes), 1)

        # Guardrail against "no data => everyone silent" false positives.
        min_covered_nodes = 3
        min_coverage_ratio = 0.30
        if comm_edges == 0 or covered_nodes < min_covered_nodes or coverage_ratio < min_coverage_ratio:
            return []

        for dev in self.nb.collaboration_graph.nodes():
            collab_deg = self.nb.collaboration_graph.degree(dev)
            comm_deg = self.nb.communication_graph.degree(dev) \
                if self.nb.communication_graph.has_node(dev) else 0
            if collab_deg >= 3 and comm_deg == 0:
                smells.append(SmellInstance(
                    smell_id="radio_silence",
                    name="Radio Silence",
                    type="Community",
                    description=(
                        f"{dev} collaborates heavily on code "
                        "but never communicates."
                    ),
                    affected_entities=[dev],
                    message=(
                        f"Radio silence: {dev} has no communication "
                        "despite high code coupling."
                    )
                ))
        return smells

    # ─────────────────────────────────────────────── entry point ────────────
    def detect_all(self) -> List[SmellInstance]:
        smells = []
        smells.extend(self.detect_organisational_silo())
        smells.extend(self.detect_lone_wolf())
        smells.extend(self.detect_bottleneck())
        smells.extend(self.detect_black_cloud())
        smells.extend(self.detect_radio_silence())
        return smells
