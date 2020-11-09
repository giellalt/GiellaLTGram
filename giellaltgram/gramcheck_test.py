#!/usr/bin/env python3
# -*- coding:utf-8 -*-

# Copyright © 2020 UiT The Arctic University of Norway
# License: GPL3
# Author: Børre Gaup <borre.gaup@uit.no>
"""Check if grammarchecker tests pass."""

import json
import sys
from argparse import ArgumentParser
from io import StringIO
from pathlib import Path
from subprocess import PIPE, Popen

import yaml
from lxml import etree

from corpustools import errormarkup, util

COLORS = {
    "red": "\033[1;31m",
    "green": "\033[0;32m",
    "orange": "\033[0;33m",
    "yellow": "\033[1;33m",
    "blue": "\033[0;34m",
    "light_blue": "\033[0;36m",
    "reset": "\033[m"
}


def colourise(string, *args, **kwargs):
    kwargs.update(COLORS)
    return string.format(*args, **kwargs)


def sortByRange(error):
    return error[1:2]


def make_errormarkup(sentence):
    para = etree.Element('p')
    para.text = sentence
    errormarkup.add_error_markup(para)

    return para


def yaml_reader(test_file):
    with test_file.open() as test_file:
        return yaml.load(test_file, Loader=yaml.FullLoader)


class GramChecker(object):
    def __init__(self, config, yaml_parent):
        self.config = config
        self.yaml_parent = yaml_parent

    @staticmethod
    def get_unique_double_spaces(d_errors):
        double_spaces = []
        indexes = set()
        for d_error in d_errors:
            if d_error[3] == 'double-space-before' and (
                    d_error[1], d_error[2]) not in indexes:
                double_spaces.append(d_error)
                indexes.add((d_error[1], d_error[2]))

        return double_spaces

    @staticmethod
    def remove_dupes(double_spaces, d_errors):
        for removable_error in [
                d_error for double_space in double_spaces
                for d_error in d_errors if double_space[1:2] == d_error[1:2]
        ]:
            d_errors.remove(removable_error)

    @staticmethod
    def make_new_double_space_errors(double_space, d_result):
        d_errors = d_result['errs']
        parts = double_space[0].split('  ')

        for position, part in enumerate(parts[1:], start=1):
            error = f'{parts[position - 1]}  {part}'
            start = d_result['text'].find(error)
            end = start + len(error)
            candidate = [
                error, start, end, 'double-space-before',
                f'Leat guokte gaskka ovdal "{part}"',
                [f'{parts[position - 1]} {part}'], 'Sátnegaskameattáhusat'
            ]
            if candidate not in d_errors:
                d_errors.append(candidate)

    def make_new_errors(self, double_space, d_result):
        d_errors = d_result['errs']
        parts = double_space[0].split('  ')

        error = double_space[0]
        min = 0
        max = len(error)
        position = d_errors.index(double_space)
        for new_position, part in enumerate(
            [part for part in double_space[0].split() if part],
                start=position):
            res, _, _ = self.check_grammar(part)
            part_errors = json.loads(res)['errs']
            min = error[min:max].find(part)
            for p_error in part_errors:
                p_error[1] = min + double_space[1]
                p_error[2] = min + double_space[1] + len(part)
                d_errors.insert(new_position, p_error)

    def get_unique_double_spaces(self, d_errors):
        double_spaces = []
        indexes = set()
        for d_error in d_errors:
            if d_error[3] == 'double-space-before' and (
                    d_error[1], d_error[2]) not in indexes:
                double_spaces.append(d_error)
                indexes.add((d_error[1], d_error[2]))

        return double_spaces

    def fix_no_space_after_punct_mark(self, punct_error, d_errors):
        self.remove_dupes([punct_error], d_errors)
        error_message = punct_error[4]
        current_punct = error_message[error_message.find('"') +
                                      1:error_message.rfind('"')]
        parenthesis = punct_error[0].find(current_punct)

        d_errors.append([
            punct_error[0][parenthesis:], punct_error[1] + parenthesis,
            punct_error[1] + parenthesis + len(punct_error[0][parenthesis:]),
            punct_error[3], punct_error[4],
            [f'{current_punct} {punct_error[0][parenthesis + 1:]}'],
            punct_error[6]
        ])

        part1 = punct_error[0][:parenthesis]
        start = punct_error[1]
        end = punct_error[1] + len(part1)
        if part1:
            self.add_part(part1, start, end, d_errors)

        part2 = punct_error[0][parenthesis + 1:]
        start = punct_error[1] + parenthesis + 1
        end = punct_error[1] + parenthesis + 1 + len(part2)
        if part2:
            self.add_part(part2, start, end, d_errors)

        d_errors.sort(key=sortByRange)

    def add_part(self, part, start, end, d_errors):
        res, _, _ = self.check_grammar(part)
        errors = json.loads(res)['errs']
        for error in [error for error in errors if error]:
            candidate = [
                error[0], start, end, error[3], error[4], error[5], error[6]
            ]
            if candidate not in d_errors:
                d_errors.append(candidate)

    def fix_no_space_before_parent_start(self, space_error, d_errors):
        for dupe in [
                d_error for d_error in d_errors
                if d_error[1:2] == space_error[1:2]
        ]:
            d_errors.remove(dupe)

        parenthesis = space_error[0].find('(')
        d_errors.append([
            space_error[0][parenthesis:], space_error[1] + parenthesis,
            space_error[2], space_error[3], space_error[4], [' ('],
            space_error[6]
        ])
        part1 = space_error[0][:parenthesis]
        start = space_error[1]
        end = space_error[1] + len(part1)
        if part1:
            self.add_part(part1, start, end, d_errors)

        part2 = space_error[0][parenthesis + 1:]
        start = space_error[1] + parenthesis + 1
        end = space_error[1] + parenthesis + 1 + len(part2)
        if part2:
            self.add_part(part2, start, end, d_errors)

        d_errors.sort(key=sortByRange)

    def fix_aistton(self, d_errors, position):
        d_error = d_errors[position]
        if d_error[3] == 'punct-aistton-left' and len(d_error[0]) > 1:
            sentence = d_error[0][1:]
            d_error[0] = d_error[0][0]
            d_error[5] = ['”']
            d_error[2] = d_error[1] + 1

            res, _, _ = self.check_grammar(sentence)
            new_d_error = json.loads(res)['errs']
            if new_d_error:
                new_d_error[0][1] = d_error[1] + 1
                new_d_error[0][2] = d_error[1] + 1 + len(sentence)
                d_errors.insert(position + 1, new_d_error[0])

        if d_error[3] == 'punct-aistton-right' and len(d_error[0]) > 1:
            sentence = d_error[0][:-1]
            d_error[0] = d_error[0][-1]
            d_error[5] = ['”']
            d_error[1] = d_error[2] - 1

            res, _, _ = self.check_grammar(sentence)
            new_d_error = json.loads(res)['errs']
            if new_d_error:
                new_d_error[0][1] = d_error[1] - len(sentence)
                new_d_error[0][2] = d_error[1]
                d_errors.insert(position, new_d_error[0])

        if d_error[3] == 'punct-aistton-both':
            previous_error = d_errors[position - 1]
            remove_previous = previous_error[1] == d_error[
                1] and previous_error[2] == d_error[2] and previous_error[
                    3] == 'typo'

            sentence = d_error[0][1:-1]

            right_error = [part for part in d_error]
            right_error[0] = right_error[0][-1]
            right_error[5] = ['”']
            right_error[1] = right_error[2] - 1
            right_error[3] = 'punct-aistton-right'
            d_errors.insert(position + 1, right_error)

            d_error[0] = d_error[0][0]
            d_error[5] = ['”']
            d_error[2] = d_error[1] + 1
            d_error[3] = 'punct-aistton-left'

            res, _, _ = self.check_grammar(sentence)
            new_d_error = json.loads(res)['errs']
            if new_d_error:
                new_d_error[0][1] = d_error[1] + 1
                new_d_error[0][2] = d_error[1] + 1 + len(sentence)
                d_errors.insert(position + 1, new_d_error[0])

            if remove_previous:
                del d_errors[position - 1]

    def fix_double_space(self, d_result):
        d_errors = d_result['errs']

        double_spaces = self.get_unique_double_spaces(d_errors)
        self.remove_dupes(double_spaces, d_errors)

        for double_space in double_spaces:
            self.make_new_double_space_errors(double_space, d_result)

        new_double_spaces = self.get_unique_double_spaces(d_errors)

        for new_double_space in new_double_spaces:
            self.make_new_errors(new_double_space)

        d_errors.sort(key=sortByRange)

    def get_error_corrections(self, para):
        parts = []
        if para.text is not None:
            parts.append(para.text)
        for child in para:
            parts.append(child.get('correct'))
            for grandchild in child:
                parts.append(self.get_error_corrections(grandchild))

        if not len(para) and para.tail:
            parts.append(para.tail)

        return ''.join(parts)

    def extract_error_info(self, parts, errors, para):
        info = {}
        if para.tag.startswith('error'):
            for name, value in para.items():
                info[name] = value
            info['type'] = para.tag
            info['start'] = len("".join(parts))
            info['error'] = self.get_error_corrections(para) if len(
                para) else para.text

        if para.text:
            parts.append(para.text)

        for child in para:
            errors.append(self.extract_error_info(parts, errors, child))

        if para.tag.startswith('error'):
            info['end'] = len("".join(parts))

        if para.tail:
            parts.append(para.tail)

        return info

    def fix_all_errors(self, d_result):
        """Remove errors that cover the same area of the typo and msyn types."""
        d_errors = d_result['errs']

        self.fix_double_space(d_result)

        if any(
            [d_error[3].startswith('punct-aistton') for d_error in d_errors]):
            for d_error in d_errors:
                self.fix_aistton(d_errors, d_errors.index(d_error))

        for d_error in d_errors:
            if d_error[3] == 'no-space-before-parent-start':
                self.fix_no_space_before_parent_start(d_error, d_errors)
            if d_error[3] == 'no-space-after-punct-mark':
                self.fix_no_space_after_punct_mark(d_error, d_errors)

        return d_result

    def check_sentence(self, sentence):
        res, err, returncode = self.check_grammar(sentence)

        try:
            return self.fix_all_errors(json.loads(res))['errs']
        except json.decoder.JSONDecodeError:
            return f'ERROR: {sentence} {err.decode("utf8")}'

    def get_data(self, sentence):
        parts = []
        errors = []
        self.extract_error_info(parts, errors, make_errormarkup(sentence))

        return {
            'uncorrected': ''.join(parts),
            'expected_errors': errors,
            'gramcheck_errors': self.check_sentence(''.join(parts))
        }

    @property
    def app(self):
        config = self.config

        if config.get('Archive'):
            return (f'{config.get("App")} '
                    f'--archive {self.yaml_parent}/{config.get("Archive")}')

        return (f'{config.get("App")} '
                f'--spec {self.yaml_parent}/{config.get("Spec")} '
                f'--variant {config.get("Variant")}')

    def check_grammar(self, sentence):
        runner = util.ExternalCommandRunner()
        runner.run(self.app.split(), to_stdin=sentence.encode('utf-8'))

        return runner.stdout, runner.stderr, runner.returncode


class GramTest(object):
    explanations = {
        'tp':
        'GramDivvun found marked up error and has the suggested correction',
        'fp1':
        'GramDivvun found manually marked up error, but corrected wrongly',
        'fp2': 'GramDivvun found error which is not manually marked up',
        'fn1':
        'GramDivvun found manually marked up error, but has no correction',
        'fn2': 'GramDivvun did not find manually marked up error'
    }

    class AllOutput():
        def __init__(self, args):
            self._io = StringIO()
            self.args = args

        def __str__(self):
            return self._io.getvalue()

        def write(self, data):
            self._io.write(data)

        def info(self, data):
            self.write(data)

        def title(self, *args):
            pass

        def success(self, *args):
            pass

        def failure(self, *args):
            pass

        def false_positive_1(self, *args):
            pass

        def result(self, *args):
            pass

        def final_result(self, passes, fails):
            self.write(
                colourise("Total passes: {green}{passes}{reset}, " +
                          "Total fails: {red}{fails}{reset}, " +
                          "Total: {light_blue}{total}{reset}\n",
                          passes=passes,
                          fails=fails,
                          total=fails + passes))

    class NormalOutput(AllOutput):
        def max80(self, header, test_case):
            all = f'{header} {test_case}'
            if len(all) < 80:
                return all, len(all)

            parts = []
            x = all[:80].rfind(' ')
            parts.append(all[:x])
            longest = len(parts[-1])
            all = f'{" " * len(header)}{all[x:]}'
            while len(all) > 80:
                x = all[:80].rfind(' ')
                parts.append(all[:x])
                if longest < len(parts[-1]):
                    longest = len(parts[-1])
                all = f'{" " * len(header)}{all[x:]}'

            parts.append(all)
            if longest < len(parts[-1]):
                longest = len(parts[-1])

            return '\n'.join(parts), longest

        def title(self, index, length, test_case):
            text, longest = self.max80(f'Test {index}/{length}:', test_case)

            self.write(colourise("{light_blue}-" * longest + '\n'))
            self.write(f'{text}' + '\n')
            self.write(colourise("-" * longest + '{reset}\n'))

        def success(self, case, total, error, correction, gramerr, errlist):
            x = colourise(
                ("[{light_blue}{case:>%d}/{total}{reset}][{green}PASS tp{reset}] "
                 + "{error}:{correction} {blue}=>{reset} "
                 + "{gramerr}:{errlist}\n") %
                len(str(total)),
                error=error,
                correction=correction,
                case=case,
                total=total,
                gramerr=gramerr,
                errlist=f'[{", ".join(errlist)}]')
            self.write(x)

        def failure(self, case, total, errtype, error, correction, gramerr,
                    errlist):
            x = colourise(
                ("[{light_blue}{case:>%d}/{total}{reset}][{red}FAIL " +
                 "{errtype}{reset}] {error}:{correction} {blue}=>{reset} " +
                 "{gramerr}:{errlist}\n") % len(str(total)),
                errtype=errtype,
                error=error,
                correction=correction,
                case=case,
                total=total,
                gramerr=gramerr,
                errlist=f'[{", ".join(errlist)}]')
            self.write(x)

        def result(self, number, passes, fails):
            text = colourise("Test {number} - Passes: {green}{passes}{reset}, " +
                             "Fails: {red}{fails}{reset}, " +
                             "Total: {light_blue}{total}{reset}\n\n",
                             number=number,
                             passes=passes,
                             fails=fails,
                             total=passes + fails)
            self.write(text)

    def __init__(self, args):
        self.args = args
        self.config = self.load_config()
        self.fails = 0
        self.passes = 0

    def load_config(self):
        args = self.args
        config = {}

        if args.silent:
            config['out'] = GramTest.NoOutput(args)
        else:
            config['out'] = {
                "normal": GramTest.NormalOutput,
                # "terse": MorphTest.TerseOutput,
                # "compact": MorphTest.CompactOutput,
                # "silent": MorphTest.NoOutput,
                # "final": MorphTest.FinalOutput
            }.get(args.output, lambda x: None)(args)

        test_file = Path(args.test_file)
        if test_file.is_file():
            config['test_file'] = test_file
        else:
            raise IOError(f'Test file {args.testfile} does not exist:')

        if not args.colour:
            for key in list(COLORS.keys()):
                COLORS[key] = ""

        return config

    @property
    def tests(self):
        yaml = yaml_reader(self.config.get('test_file'))

        grammarchecker = GramChecker(yaml.get('Config'), self.config['test_file'].parent)
        return {test: grammarchecker.get_data(test) for test in yaml['Tests']}

    def run_tests(self):
        tests = self.tests
        for item in enumerate(tests.items(), start=1):
            self.run_test(item, len(tests))

        self.config.get('out').final_result(self.passes, self.fails)

    def run_test(self, item, length):
        count = {'Pass': 0, 'Fail': 0}

        out = self.config.get('out')
        out.title(item[0], length, item[1][0])

        expected_errors = item[1][1]['expected_errors']
        gramcheck_errors = item[1][1]['gramcheck_errors']

        corrects = self.correct_in_dc(expected_errors, gramcheck_errors)
        if corrects:
            for correct in corrects:
                count['Pass'] += 1
                out.success(item[0], length, correct[0]["error"],
                            correct[0]["correct"], correct[1][0], correct[1][5])

        false_positives_1 = self.correct_not_in_dc(expected_errors,
                                                   gramcheck_errors)
        if false_positives_1:
            for false_positive_1 in false_positives_1:
                count['Fail'] += 1
                out.failure(item[0], length, 'fp1',
                            false_positive_1[0]["error"],
                            false_positive_1[0]["correct"],
                            false_positive_1[1][0],
                            false_positive_1[1][5])

        false_positives_2 = self.dcs_not_in_correct(expected_errors,
                                                    gramcheck_errors)
        if false_positives_2:
            for false_positive_2 in false_positives_2:
                count['Fail'] += 1
                out.failure(item[0], length, 'fp2', '', '', false_positive_2[0],
                            false_positive_2[5])

        false_negatives_1 = self.correct_no_suggestion_in_dc(
            expected_errors, gramcheck_errors)
        for false_negative_1 in false_negatives_1:
            count['Fail'] += 1
            out.failure(item[0], length, 'fn1', false_negative_1[0]["error"],
                        false_negative_1[0]["correct"], false_negative_1[1][0],
                        false_negative_1[1][5])

        false_negatives_2 = self.corrects_not_in_dc(expected_errors,
                                                    gramcheck_errors)
        for false_negative_2 in false_negatives_2:
            count['Fail'] += 1
            out.failure(item[0], length, 'fn2', false_negative_2["error"],
                        false_negative_2["correct"], '', [])

        out.result(item[0], count['Pass'], count['Fail'])

        self.passes += count['Pass']
        self.fails += count['Fail']

    def has_same_range_and_error(self, c_error, d_error):
        if d_error[3] == 'double-space-before':
            return c_error['start'] == d_error[1] and c_error[
                'end'] == d_error[2]
        else:
            return c_error['start'] == d_error[1] and c_error[
                'end'] == d_error[2] and c_error['error'] == d_error[0]

    def has_suggestions_with_hit(self, c_error, d_error):
        return self.has_same_range_and_error(
            c_error,
            d_error) and d_error[5] and c_error['correct'] in d_error[5]

    def correct_in_dc(self, correct, dc):
        return [(c_error, d_error) for c_error in correct for d_error in dc
                if self.has_suggestions_with_hit(c_error, d_error)]

    def correct_not_in_dc(self, correct, dc):
        return [(c_error, d_error) for c_error in correct for d_error in dc
                if self.has_suggestions_without_hit(c_error, d_error)]

    def has_suggestions_without_hit(self, c_error, d_error):
        return self.has_same_range_and_error(
            c_error,
            d_error) and d_error[5] and c_error['correct'] not in d_error[5]

    def dcs_not_in_correct(self, correct, dc):
        corrects = []
        for d_error in dc:
            for c_error in correct:
                if self.has_same_range_and_error(c_error, d_error):
                    break
            else:
                corrects.append(d_error)

        return corrects

    def corrects_not_in_dc(self, c_errors, d_errors):
        corrects = []
        for c_error in c_errors:
            for d_error in d_errors:
                if self.has_same_range_and_error(c_error, d_error):
                    break
            else:
                corrects.append(c_error)

        return corrects

    def correct_no_suggestion_in_dc(self, correct, dc):
        return [(c_error, d_error) for c_error in correct for d_error in dc
                if self.has_no_suggestions(c_error, d_error)]

    def has_no_suggestions(self, c_error, d_error):
        return self.has_same_range_and_error(c_error,
                                             d_error) and not d_error[5]

    def run(self):
        self.run_tests()

        return 1 if self.fails else 0

    def __str__(self):
        return str(self.config.get('out'))


class UI(ArgumentParser):
    def __init__(self):
        ArgumentParser.__init__(self)

        self.description = "Test errormarkuped up sentences"
        self.add_argument("-c",
                          "--colour",
                          dest="colour",
                          action="store_true",
                          help="Colours the output")
        self.add_argument("-o",
                          "--output",
                          choices=['normal', 'compact', 'terse', 'final'],
                          dest="output",
                          default="normal",
                          help="""Desired output style (Default: normal)""")
        self.add_argument("-q",
                          "--silent",
                          dest="silent",
                          action="store_true",
                          help="Hide all output; exit code only")
        self.add_argument(
            "-p",
            "--hide-passes",
            dest="hide_pass",
            action="store_true",
            help="Suppresses passes to make finding fails easier")
        self.add_argument(
            "-t",
            "--test",
            dest="test",
            nargs='?',
            required=False,
            help="""Which test to run (Default: all). TEST = test ID, e.g.
            'Noun - g\u00E5etie' (remember quotes if the ID contains spaces)"""
        )
        self.add_argument("-v",
                          "--verbose",
                          dest="verbose",
                          action="store_true",
                          help="More verbose output.")
        self.add_argument("test_file", help="YAML file with test rules")

        self.test = GramTest(self.parse_args())

    def start(self):
        ret = self.test.run()
        sys.stdout.write(str(self.test))
        sys.exit(ret)


def main():
    try:
        ui = UI()
        ui.start()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()