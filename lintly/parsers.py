# -*- coding: utf-8 -*-
"""
Parsers accept linter output and return file paths and all of the violations in that file.
"""
import collections
import json
import os
import re

from .violations import Violation


class BaseLintParser(object):

    def parse_violations(self, output):
        raise NotImplementedError

    def _get_working_dir(self):
        return os.getcwd()

    def _normalize_path(self, path):
        """
        Normalizes a file path so that it returns a path relative to the root repo directory.
        """
        norm_path = os.path.normpath(path)
        return os.path.relpath(norm_path, start=self._get_working_dir())


class LineRegexParser(BaseLintParser):
    """
    A parser that runs a regular expression on each line of the output to return violations.
    The regex should match the following capture groups:

        - path
        - line
        - column
        - code
        - message
    """

    def __init__(self, regex):
        self.regex = regex

    def parse_violations(self, output):
        violations = collections.defaultdict(list)

        line_regex = re.compile(self.regex)

        # Collect all the issues into a dict where the keys are the file paths and the values are a
        # list of the issues in that file.
        for line in output.strip().splitlines():
            clean_line = line.strip()

            match = line_regex.match(clean_line)

            if not match:
                continue

            path = self._normalize_path(match.group('path'))

            violation = Violation(
                line=int(match.group('line')),
                column=int(match.group('column')),
                code=match.group('code'),
                message=match.group('message')
            )

            violations[path].append(violation)

        return violations


class PylintJSONParser(BaseLintParser):
    """
    Pylint JSON format:

        [
            {
                "type": "convention",
                "module": "lintly.backends.base",
                "obj": "BaseGitBackend.post_status",
                "line": 54,
                "column": 4,
                "path": "lintly/backends/base.py",
                "symbol": "missing-docstring",
                "message": "Missing method docstring",
                "message-id": "C0111"
            }
        ]
    """

    def parse_violations(self, output):
        # Sometimes pylint will output "No config file found, using default configuration".
        # This handles that case by removing that line.
        if output and output.startswith('No config'):
            output = '\n'.join(output.splitlines()[1:])

        output = output.strip()
        if not output:
            return dict()

        json_data = json.loads(output)

        violations = collections.defaultdict(list)

        for violation_json in json_data:
            violation = Violation(
                line=violation_json['line'],
                column=violation_json['column'],
                code='{} ({})'.format(violation_json['message-id'], violation_json['symbol']),
                message=violation_json['message']
            )

            path = self._normalize_path(violation_json['path'])
            violations[path].append(violation)

        return violations


class ESLintParser(BaseLintParser):

    def parse_violations(self, output):
        violations = collections.defaultdict(list)

        current_file = None

        # Collect all the issues into a dict where the keys are the file paths and the values are a
        # list of the issues in that file.
        for line in output.strip().splitlines():
            if line.startswith(' '):
                # This line is a linting violation
                regex = r'^(?P<line>\d+):(?P<column>\d+)\s+(error|warning)\s+(?P<message>.*)\s+(?P<code>.+)$'
                match = re.match(regex, line.strip())

                violation = Violation(
                    line=int(match.group('line')),
                    column=int(match.group('column')),
                    code=match.group('code').strip(),
                    message=match.group('message').strip()
                )
                violations[current_file].append(violation)
            elif line.startswith('✖'):
                # We're at the end of the file
                break
            else:
                # This line is a file path
                current_file = self._normalize_path(line)

        return violations


class StylelintParser(BaseLintParser):

    def parse_violations(self, output):
        violations = collections.defaultdict(list)

        current_file = None

        # Collect all the issues into a dict where the keys are the file paths and the values are a
        # list of the issues in that file.
        for line in output.strip().splitlines():
            if line.startswith(' '):
                # This line is a linting violation
                regex = r'^(?P<line>\d+):(?P<column>\d+)\s+✖\s+(?P<message>.*)\s+(?P<code>.+)$'
                match = re.match(regex, line.strip())

                violation = Violation(
                    line=int(match.group('line')),
                    column=int(match.group('column')),
                    code=match.group('code').strip(),
                    message=match.group('message').strip()
                )
                violations[current_file].append(violation)
            else:
                # This line is a file path
                current_file = self._normalize_path(line)

        return violations


class BlackParser(BaseLintParser):
    """A parser for the `black [source] --check` command."""

    def parse_violations(self, output):
        violations = {}
        for line in output.strip().splitlines():
            # That means a file needs to be formatted by `black`.
            if line.startswith('would reformat '):
                # Last part is the file path.
                path = self._normalize_path(line.split(' ')[-1])
                violations[path] = [Violation(
                    line=1, column=1, code='`black`', message='this file needs to be formatted'
                )]
        return violations


class CfnLintParser(BaseLintParser):
    """A parser for the `cfn-lint` command.

      cfn-lint output example:

      W2001 Parameter UnusedParameter not used.
      template.yaml:2:9
    """

    def parse_violations(self, output):
        violations = collections.defaultdict(list)

        regex = re.compile(r"[EW]\d{4}\s")

        next_line_is_path = False
        current_violation = None
        for line in output.strip().splitlines():
            if regex.match(line):
                # This line is a cfn-lint error or warning
                next_line_is_path = True
                current_violation = line
            elif next_line_is_path:
                # This line is a filepath:line_number:column_number
                path, line_number, column = line.split(":")
                path = self._normalize_path(path)

                code, message = current_violation.split(" ", 1)

                violation = Violation(line=int(line_number),
                                      column=int(column),
                                      code=code,
                                      message=message)
                violations[path].append(violation)

                next_line_is_path = False
                current_violation = None

        return violations


class BanditJSONParser(BaseLintParser):
    """
    Bandit JSON format:

      [
          {
              "errors": [],
              "generated_at": "2021-01-07T23:39:39Z",
              "metrics": {
                  "./lintly/formatters.py": {
                      "CONFIDENCE.HIGH": 1.0,
                      "CONFIDENCE.LOW": 0.0,
                      "CONFIDENCE.MEDIUM": 0.0,
                      "CONFIDENCE.UNDEFINED": 0.0,
                      "SEVERITY.HIGH": 1.0,
                      "SEVERITY.LOW": 0.0,
                      "SEVERITY.MEDIUM": 0.0,
                      "SEVERITY.UNDEFINED": 0.0,
                      "loc": 31,
                      "nosec": 0
                      },
              "results": [
                  {
                      "code": "13 \n14 env = Environment(\n15 loader=FileSystemLoader(TEMPLATES_PATH),
                                  \n16 autoescape=False\n17 )\n",
                      "filename": "./lintly/formatters.py",
                      "issue_confidence": "HIGH",
                      "issue_severity": "HIGH",
                      "issue_text": "Using jinja2 templates with autoescape=False is dangerous and can lead to XSS."
                                    "Use autoescape=True or use the select_autoescape function.",
                      "line_number": 14,
                      "line_range": [
                          14,
                          15,
                          16
                          ],
                     "more_info": "https://bandit.readthedocs.io/en/latest/plugins/b701_jinja2_autoescape_false.html",
                     "test_id": "B701"
                     "test_name": "jinja2_autoescape_false"
                }
            ]
         }
     ]

    """

    def parse_violations(self, output):

        output = output.strip()
        if not output:
            return dict()

        json_data = json.loads(output)

        violations = collections.defaultdict(list)
        for violation_json in json_data["results"]:
            violation = Violation(
                line=violation_json["line_number"],
                column=0,
                code="{} ({})".format(
                    violation_json["test_id"], violation_json["test_name"]
                ),
                message=violation_json["issue_text"],
            )

            path = self._normalize_path(violation_json["filename"])
            violations[path].append(violation)

        return violations


class CfnNagParser(BaseLintParser):

    def parse_violations(self, output):

        file_list = json.loads(output)
        violations = {}

        for file in file_list:
            file_violations = []
            for violation_info in file["file_results"]["violations"]:
                for line_number in violation_info["line_numbers"]:
                    violation = Violation(
                        line=line_number,
                        column=0,
                        code=violation_info["id"],
                        message=violation_info["message"]
                    )

                    file_violations.append(violation)

            path = self._normalize_path(file["filename"])
            violations[path] = file_violations

        return violations


class GitLeaksParser(BaseLintParser):
    """
    Gitleaks JSON format

        {
            "line": "-----BEGIN PRIVATE KEY-----",
            "lineNumber": 59,
            "offender": "-----BEGIN PRIVATE KEY-----",
            "commit": "111111111111111111111000000000",
            "repo": ".",
            "repoURL": "",
            "leakURL": "",
            "rule": "Asymmetric Private Key",
            "commitMessage": "any commit message \n",
            "author": "bob s",
            "email": "bob@example.com",
            "file": "relative/path/to/output",
            "date": "2020-04-14T15:17:53-07:00",
            "tags": "key, AsymmetricPrivateKey"
        }

    """

    def parse_violations(self, output):
        if not output:
            return dict()

        json_data = json.loads(output)

        violations = collections.defaultdict(list)
        for violation_data in json_data:
            violation = Violation(
                line=violation_data["lineNumber"],
                column=0,
                code=violation_data["offender"],
                message=violation_data["rule"]
            )

            path = self._normalize_path(violation_data['file'])
            violations[path].append(violation)

        return violations


class HadolintParser(BaseLintParser):
    """
    Hadolint JSON format

       {
            "line": 20,
            "code": "DL3020",
            "message": "Use COPY instead of ADD for files and folders",
            "column": 1,
            "file": "cfn-nag-lintly-action/Dockerfile",
            "level": "error"
        }

    """

    def parse_violations(self, output):
        if not output:
            return dict()

        json_data = json.loads(output)

        violations = collections.defaultdict(list)

        for violation_json in json_data:
            violation = Violation(
                line=violation_json['line'],
                column=violation_json['column'],
                code=violation_json["code"],
                message=violation_json['message']
            )

            path = self._normalize_path(violation_json['file'])
            violations[path].append(violation)

        return violations


DEFAULT_PARSER = LineRegexParser(r'^(?P<path>.*):(?P<line>\d+):(?P<column>\d+): (?P<code>\w\d+) (?P<message>.*)$')


PARSERS = {
    # Default flake8 format
    # docs/conf.py:230:1: E265 block comment should start with '# '
    # path:line:column: CODE message
    'unix': DEFAULT_PARSER,
    'flake8': DEFAULT_PARSER,

    # Pylint ---output-format=json
    'pylint-json': PylintJSONParser(),

    # ESLint's default formatter
    # /Users/grant/project/file1.js
    #     1:1    error  '$' is not defined                              no-undef
    'eslint': ESLintParser(),

    # ESLint's unix formatter
    # lintly/static/js/scripts.js:69:1: 'lintly' is not defined. [Error/no-undef]
    # path:line:column: message [CODE]
    'eslint-unix': LineRegexParser(r'^(?P<path>.*):(?P<line>\d+):(?P<column>\d+): '
                                   r'(?P<message>.+) \[(Warning|Error)/(?P<code>.+)\]$'),

    # Stylelint's default formatter
    # lintly/static/sass/file1.scss
    #   13:1  ✖  Expected no more than 1 empty line   max-empty-lines
    'stylelint': StylelintParser(),

    # Black's check command default formatter.
    'black': BlackParser(),

    # cfn-lint default formatter
    'cfn-lint': CfnLintParser(),

    # Bandit Parser
    "bandit-json": BanditJSONParser(),

    # cfn-nag JSON output
    'cfn-nag': CfnNagParser(),

    # gitleaks JSON Parser
    "gitleaks": GitLeaksParser(),

    # hadolint JSON output
    "hadolint": HadolintParser(),
}
