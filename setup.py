from setuptools import setup

setup(name='legacy-runtime-rebuilder', version='0.1.1',
      description='Prepare and verify legacy PHP security rebuilds',
      packages=['runtime_rebuilder'], package_data={'runtime_rebuilder': ['catalog.json']},
      python_requires='>=3.6', license='MIT',
      entry_points={'console_scripts': ['rebuildctl=runtime_rebuilder.cli:main']})
