import os
import time
import threading
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from components.inspector import Inspector
from utils.file_utils import FileUtils


_global_inspector_per_process: Inspector | None = None

def _process_worker_inspect(filename: str, output_path: str) -> tuple[pd.DataFrame, int, Exception | None]:
    global _global_inspector_per_process
    try:
        if _global_inspector_per_process is None:
            _global_inspector_per_process = Inspector(output_path)
        
        result_df = _global_inspector_per_process.inspect(filename)
        smell_count = len(result_df)
        if smell_count > 0:
            print(f"Found {smell_count} code smells in file: {filename}")
        return result_df, smell_count, None
    except Exception as e:
        return pd.DataFrame(), 0, e


class ProjectAnalyzer:
    """
    Handles the analysis of Python projects
    and manages all file-related operations.
    """

    def __init__(self, output_path: str):
        """
        Initializes the ProjectAnalyzer.

        Parameters:
        - output_path (str): Directory where analysis results will be saved.
        """
        self.base_output_path = output_path
        self.output_path = os.path.join(output_path, "output")

        FileUtils.clean_directory(self.base_output_path, "output")

        self.inspector = Inspector(self.output_path)
        self._thread_local = threading.local()

    def clean_output_directory(self):
        """
        Cleans or creates the output directory for analysis results.
        """
        FileUtils.clean_directory(self.base_output_path, "output")

    def _save_results(self, df: pd.DataFrame, filename: str):
        """
        Saves the DataFrame to a CSV file in the output root folder.
        """
        if df.empty:
            print(f"No results to save for {filename}")
            return

        os.makedirs(self.output_path, exist_ok=True)

        file_path = os.path.join(self.output_path, filename)
        df.to_csv(file_path, index=False)
        print(f"Results saved to {file_path}")

    @staticmethod
    def _empty_results_dataframe() -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "filename",
                "function_name",
                "smell_name",
                "line",
                "description",
                "additional_info",
            ]
        )

    def _build_inspector(self) -> Inspector:
        return Inspector(self.output_path)

    def _get_thread_inspector(self) -> Inspector:
        inspector = getattr(self._thread_local, "inspector", None)
        if inspector is None:
            inspector = self._build_inspector()
            self._thread_local.inspector = inspector
        return inspector

    def _append_analysis_error(self, filename: str, error: Exception):
        error_file = os.path.join(self.output_path, "error.txt")
        os.makedirs(self.output_path, exist_ok=True)
        with open(error_file, "a") as f:
            f.write(f"Error in file {filename}: {str(error)}\n")
        print(f"Error analyzing file: {filename} - {str(error)}")

    def _inspect_with_error_handling(
        self, filename: str, inspector: Inspector
    ) -> tuple[pd.DataFrame, int]:
        result = inspector.inspect(filename)
        smell_count = len(result)
        if smell_count > 0:
            print(f"Found {smell_count} code smells in file: {filename}")
        return result, smell_count

    def _inspect_in_worker(self, filename: str) -> tuple[pd.DataFrame, int]:
        return self._inspect_with_error_handling(
            filename, self._get_thread_inspector()
        )

    def _analyze_filenames(
        self,
        filenames: list[str],
        max_workers: int = 1,
        use_thread_local_inspector: bool = False,
    ) -> tuple[pd.DataFrame, int]:
        ordered_results: list[pd.DataFrame | None] = [None] * len(filenames)
        total_smells = 0

        if max_workers <= 1:
            inspector = (
                self._get_thread_inspector()
                if use_thread_local_inspector
                else self.inspector
            )
            for index, filename in enumerate(filenames):
                try:
                    result, smell_count = self._inspect_with_error_handling(
                        filename, inspector
                    )
                    ordered_results[index] = result
                    total_smells += smell_count
                except (SyntaxError, FileNotFoundError) as error:
                    self._append_analysis_error(filename, error)
                    continue
        else:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_context = {
                    executor.submit(_process_worker_inspect, filename, self.output_path): (
                        index,
                        filename,
                    )
                    for index, filename in enumerate(filenames)
                }
                for future in as_completed(future_to_context):
                    index, filename = future_to_context[future]
                    result, smell_count, error = future.result()
                    if error:
                        self._append_analysis_error(filename, error)
                    else:
                        ordered_results[index] = result
                        total_smells += smell_count

        result_frames = [
            result
            for result in ordered_results
            if result is not None and not result.empty
        ]
        if not result_frames:
            return self._empty_results_dataframe(), total_smells
        return pd.concat(result_frames, ignore_index=True), total_smells

    def analyze_project(
        self,
        project_path: str,
        generate_graph: bool = False,
        max_workers: int = 1,
    ) -> int:
        """
        Analyzes a single project for code smells.

        Parameters:
        - project_path (str): Path to the project to be analyzed.
        - generate_graph (bool): Whether to generate a call graph.
        - max_workers (int): Maximum number of file-analysis workers.

        Returns:
        - int: Total number of code smells found in the project.
        """
        project_name = os.path.basename(os.path.normpath(project_path))

        print(f"Starting analysis for project: {project_name}")

        filenames = FileUtils.get_python_files(project_path)
        if not filenames:
            raise ValueError(f"The project '{project_path}' contains no Python files.")
        worker_count = max(1, min(max_workers, len(filenames)))
        to_save, total_smells = self._analyze_filenames(
            filenames, max_workers=worker_count
        )

        self._save_results(to_save, "overview.csv")

        if generate_graph:
            try:
                from components.dependency_graph_builder import DependencyGraphBuilder
                graph_builder = DependencyGraphBuilder(self.output_path)
                graph_builder.build_graph(filenames)
            except Exception as e:
                print(f"Error building call graph: {e}")

        print(f"Finished analysis for project: {project_name}")
        print(
            f"Total code smells found in project "
            f"'{project_name}': {total_smells}\n"
        )
        return total_smells

    def analyze_projects_sequential(
        self, base_path: str, resume: bool = False, generate_graph: bool = False
    ):
        """
        Sequentially analyzes multiple projects.

        Parameters:
        - base_path (str): Directory containing projects to be analyzed.
        - resume (bool): Whether to resume from the last analyzed project.
        - generate_graph (bool): Whether to generate a call graph.
        """
        execution_log_path = os.path.join(base_path, "execution_log.txt")
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        if not resume:
            FileUtils.initialize_log(execution_log_path)

        last_project = (
            FileUtils.get_last_logged_project(execution_log_path)
            if resume
            else ""
        )

        start_time = time.time()
        total_smells = 0

        for dirname in os.listdir(base_path):
            if dirname in {"output", "execution_log.txt"}:
                continue

            if resume and dirname <= last_project:
                continue

            project_path = os.path.join(base_path, dirname)

            if not os.path.isdir(project_path):
                continue

            print(f"Analyzing project '{dirname}' sequentially...")
            try:
                filenames = FileUtils.get_python_files(project_path)
                to_save, project_smells = self._analyze_filenames(filenames)

                if not to_save.empty:
                    details_path = os.path.join(
                        self.output_path, "project_details"
                    )
                    os.makedirs(details_path, exist_ok=True)
                    detailed_file_path = os.path.join(
                        details_path, f"{dirname}_results.csv"
                    )
                    to_save.to_csv(detailed_file_path, index=False)
                    print(f"Detailed results saved to {detailed_file_path}")

                if generate_graph:
                    try:
                        from components.dependency_graph_builder import DependencyGraphBuilder
                        graph_path = os.path.join(self.output_path, "graphs", dirname)
                        graph_builder = DependencyGraphBuilder(graph_path)
                        graph_builder.build_graph(filenames)
                    except Exception as e:
                        print(f"Error building call graph for {dirname}: {e}")

                total_smells += project_smells
                print(
                    f"Project '{dirname}' analyzed successfully."
                    f"Code smells found: {project_smells}\n"
                )

                FileUtils.append_to_log(execution_log_path, dirname)

            except Exception as e:
                print(f"Error analyzing project '{dirname}': {str(e)}\n")

        print(
            "Sequential execution completed in "
            f"{time.time() - start_time:.2f} seconds."
        )
        print(f"Total code smells found in all projects: {total_smells}\n")

    def analyze_projects_parallel(self, base_path: str, max_workers: int, generate_graph: bool = False):
        """
        Analyzes multiple projects in parallel.

        Parameters:
        - base_path (str): Directory containing projects to be analyzed.
        - max_workers (int): Maximum number of parallel threads.
        - generate_graph (bool): Whether to generate a call graph.
        """
        execution_log_path = os.path.join(base_path, "execution_log.txt")
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        if not os.path.exists(execution_log_path):
            FileUtils.initialize_log(execution_log_path)

        start_time = time.time()
        total_smells = 0
        lock = threading.Lock()  # Thread-safe lock for logging

        def analyze_and_count_smells(dirname: str):
            nonlocal total_smells
            project_path = os.path.join(base_path, dirname)
            if dirname in {"output", "execution_log.txt"} or not os.path.isdir(
                project_path
            ):
                return

            print(f"Analyzing project '{dirname}' in parallel...")
            try:
                filenames = FileUtils.get_python_files(project_path)
                to_save, project_smells = self._analyze_filenames(
                    filenames, use_thread_local_inspector=True
                )

                if not to_save.empty:
                    details_path = os.path.join(
                        self.output_path, "project_details"
                    )
                    os.makedirs(details_path, exist_ok=True)
                    detailed_file_path = os.path.join(
                        details_path, f"{dirname}_results.csv"
                    )
                    to_save.to_csv(detailed_file_path, index=False)
                    print(f"Detailed results saved to {detailed_file_path}")

                if generate_graph:
                    try:
                        from components.dependency_graph_builder import DependencyGraphBuilder
                        graph_path = os.path.join(self.output_path, "graphs", dirname)
                        graph_builder = DependencyGraphBuilder(graph_path)
                        graph_builder.build_graph(filenames)
                    except Exception as e:
                        print(f"Error building call graph for {dirname}: {e}")

                with lock:
                    total_smells += project_smells

                # Thread-safe log update
                FileUtils.synchronized_append_to_log(
                    execution_log_path, dirname, lock
                )

            except Exception as e:
                print(f"Error analyzing project '{dirname}': {str(e)}\n")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for dirname in os.listdir(base_path):
                executor.submit(analyze_and_count_smells, dirname)

        print(
            "Parallel execution completed in "
            f"{time.time() - start_time:.2f} seconds."
        )
        print(f"Total code smells found in all projects: {total_smells}\n")

    def merge_all_results(self):
        """
        Merges all CSV result files from multiple
        projects into a single overview CSV in the root output folder.
        """
        FileUtils.merge_results(
            input_dir=os.path.join(self.output_path, "project_details"),
            output_dir=self.output_path,
        )
