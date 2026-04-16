from setuptools import find_packages, setup

package_name = 'rostaurant_function'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/robot_function.launch.py']),
        ('share/' + package_name + '/config', ['config/robot_function.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pl3',
    maintainer_email='kyung133851@pinklab.art',
    description='Robot function execution nodes for rostaurant_state_machine integration.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'top_function_node=rostaurant_function.top.top_function_node:main',
            'follow_function_node=rostaurant_function.follow.follow_function_node:main',
            'delivery_function_node=rostaurant_function.delivery.delivery_function_node:main',
            'collect_function_node=rostaurant_function.collect.collect_function_node:main',
            'guide_function_node=rostaurant_function.guide.guide_function_node:main',
        ],
    },
)
