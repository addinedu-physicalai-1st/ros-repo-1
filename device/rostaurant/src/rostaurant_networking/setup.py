from setuptools import find_packages, setup

package_name = "rostaurant_networking"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="pinklab",
    maintainer_email="kyung133851@pinklab.art",
    description="MRTA TCP/UDP ROS2 bridge (rostaurant_networking)",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rostaurant_comm_node=rostaurant_networking.ros_bridge_node:main",
        ],
    },
)
