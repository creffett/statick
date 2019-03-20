"""Apply spotbugs tool and gather results."""

from __future__ import print_function

import os
import subprocess
import xml.etree.ElementTree as etree

from statick_tool.issue import Issue
from statick_tool.tool_plugin import ToolPlugin


class SpotbugsToolPlugin(ToolPlugin):
    """Apply spotbugs tool and gather results."""

    def get_name(self):
        """Get name of tool."""
        return "spotbugs"

    def get_tool_dependencies(self):
        """Get a list of tools that must run before this one."""
        return ["make"]

    def scan(self, package, level):
        """Run tool and gather output."""
        # Sanity check - make sure mvn exists
        if not self.command_exists('mvn'):
            print("Couldn't find 'mvn' command, can't run Spotbugs Maven integration")
            return None

        flags = ["-Dspotbugs.effort=Max", "-Dspotbugs.threshold=Low",
                 "-Dspotbugs.xmlOutput=true"]
        flags += self.get_user_flags(level)

        include_file = self.plugin_context.config.get_tool_config(self.get_name(),
                                                                  level, "include")
        exclude_file = self.plugin_context.config.get_tool_config(self.get_name(),
                                                                  level, "exclude")
        if include_file is not None:
            flags += ["-Dspotbugs.includeFilterFile={}".format(self.plugin_context
                                                               .resources.get_file(include_file))]

        if exclude_file is not None:
            flags += ["-Dspotbugs.excludeFilterFile={}".format(self.plugin_context
                                                               .resources.get_file(exclude_file))]

        issues = []
        with open(self.get_name() + ".log", "w") as f:
            for pom in package['top_poms']:
                try:
                    # The spotbugs:spotbugs-maven-plugin split is auto-concatenated
                    output = subprocess.check_output(["mvn", "com.github.spotbugs:"
                                                      "spotbugs-maven-plugin:spotbugs"] +
                                                     flags,
                                                     cwd=os.path.dirname(pom),
                                                     stderr=subprocess.STDOUT,
                                                     universal_newlines=True)
                except subprocess.CalledProcessError as ex:
                    output = ex.output
                    f.write(output)
                    print("spotbugs failed! Returncode = {}".
                          format(str(ex.returncode)))
                    print("{}".format(ex.output))
                    return None

                except OSError as ex:
                    print("Couldn't find maven! ({})".format(ex))
                    return None

                if self.plugin_context.args.show_tool_output:
                    print("{}".format(output))
                f.write(output)
            # The results will be output to (pom path)/target/spotbugs.xml for each pom
            for pom in package["all_poms"]:
                if os.path.exists(os.path.join(os.path.dirname(pom), "target", "spotbugs.xml")):
                    with open(os.path.join(os.path.dirname(pom), "target", "spotbugs.xml")) \
                            as outfile:
                        issues += self.parse_output(outfile.read())
        return issues

    def parse_output(self, output):
        """Parse tool output and report issues."""
        issues = []
        # Load the plugin mapping if possible
        warnings_mapping = self.load_mapping()
        try:
            output_xml = etree.fromstring(output)
        except etree.ParseError as ex:
            print("Couldn't parse Spotbugs output ({})! Provided output was:\n{}"
                  .format(ex, output))
            return None
        for file_entry in output_xml.findall("file"):
            # Generate the filename
            java_path_string = "{}.java".format(file_entry.attrib["classname"].replace('.', os.sep))
            file_path = ""
            for source_dir in output_xml.findall("Project/SrcDir"):
                joined_path = os.path.join(os.path.normpath(source_dir.text), java_path_string)
                if os.path.exists(joined_path):
                    file_path = joined_path
                    break
            if not file_path:
                print("Couldn't find file for class {}".format(file_entry.attrib["classname"]))
                file_path = java_path_string
            for issue in file_entry.findall("BugInstance"):
                severity = 1
                if issue.attrib["priority"] == "Normal":
                    severity = 3
                elif issue.attrib["priority"] == "High":
                    severity = 5

                cert_reference = None
                if issue.attrib["type"] in warnings_mapping:
                    cert_reference = warnings_mapping[issue.attrib["type"]]
                issues.append(Issue(file_path, issue.attrib["lineNumber"], self.get_name(),
                                    issue.attrib["type"], severity, issue.attrib["message"],
                                    cert_reference))
        return issues
