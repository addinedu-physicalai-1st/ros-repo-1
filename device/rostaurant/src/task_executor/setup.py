from glob import glob
from setuptools import find_packages, setup

package_name = "task_executor"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="pinklab",
    maintainer_email="kyung133851@pinklab.art",
    description="Task executor: /robot_command → NavigationDriver → /task_status",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "task_executor_node=task_executor.task_executor_node:main",
        ],
    },
)
