import ast
import os
from unittest.mock import mock_open, patch

import pandas as pd

from components.inspector import Inspector


def test_inspect():
    with patch("builtins.open", mock_open()) as mock_open_file, patch(
        "ast.parse"
    ) as mock_ast_parse, patch(
        "components.inspector.LibraryExtractor"
    ) as MockLibraryExtractor, patch(
        "components.inspector.VariableExtractor"
    ) as MockVariableExtractor, patch(
        "components.inspector.DataFrameExtractor"
    ) as MockDataFrameExtractor, patch(
        "components.inspector.ModelExtractor"
    ) as MockModelExtractor, patch(
        "components.inspector.RuleChecker"
    ) as MockRuleChecker:
        mock_rule_checker = MockRuleChecker.return_value
        mock_library_extractor = MockLibraryExtractor.return_value
        mock_variable_extractor = MockVariableExtractor.return_value
        mock_data_frame_extractor = MockDataFrameExtractor.return_value
        mock_model_extractor = MockModelExtractor.return_value

        mock_library_extractor.get_library_aliases.return_value = {"pandas": "pd"}
        mock_variable_extractor.extract_variable_definitions.return_value = [
            "var1",
            "var2",
        ]
        mock_data_frame_extractor.extract_dataframe_variables.return_value = [
            "df_var1",
            "df_var2",
        ]
        mock_model_extractor.model_dict = {"model1": "details"}
        mock_model_extractor.tensor_operations_dict = {
            "operation": ["tensor_op1", "tensor_op2"]
        }
        mock_model_extractor.load_model_methods.return_value = {
            "method1": "details"
        }

        mock_rule_checker.rule_check.return_value = pd.DataFrame(
            data=[
                [
                    "mock_file.py",
                    "my_function",
                    "smell1",
                    10,
                    "description1",
                    "info1",
                ],
                [
                    "mock_file.py",
                    "my_function",
                    "smell2",
                    15,
                    "description2",
                    "info2",
                ],
            ],
            columns=[
                "filename",
                "function_name",
                "smell_name",
                "line",
                "description",
                "additional_info",
            ],
        )

        mock_file_contents = """\
import pandas as pd

def my_function():
    df = pd.DataFrame()
    return df
"""
        mock_open_file.return_value.read.return_value = mock_file_contents

        mock_ast_parse.return_value = ast.Module(
            body=[
                ast.FunctionDef(
                    name="my_function",
                    args=ast.arguments(
                        args=[],
                        vararg=None,
                        kwonlyargs=[],
                        kw_defaults=[],
                        kwarg=None,
                    ),
                    body=[
                        ast.Assign(
                            targets=[ast.Name(id="df", ctx=ast.Store())],
                            value=ast.Call(
                                func=ast.Name(id="pd.DataFrame", ctx=ast.Load()),
                                args=[],
                                keywords=[],
                            ),
                        )
                    ],
                    decorator_list=[],
                    lineno=1,
                )
            ]
        )

        inspector = Inspector(output_path="mock_output_path")
        inspector.rule_checker = mock_rule_checker

        result = inspector.inspect("mock_file.py")

    mock_open_file.assert_called_once_with(
        os.path.abspath("mock_file.py"), "r", encoding="utf-8"
    )
    mock_ast_parse.assert_called_once()
    mock_model_extractor.load_model_methods.assert_called_once()
    mock_rule_checker.rule_check.assert_called_once()

    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == [
        "filename",
        "function_name",
        "smell_name",
        "line",
        "description",
        "additional_info",
    ]
    assert len(result) > 0
