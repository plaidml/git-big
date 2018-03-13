# Copyright (c) 2017 Vertex.AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

.PHONY: all clean test publish

VERSION=$(shell python -c 'import git_big; print(git_big.__version__)')

WHEEL=dist/git_big-${VERSION}-py2-none-any.whl

all: requirements-dev.txt ${WHEEL}
clean:
	rm -f requirements*.txt
	rm -rf build
	rm -rf dist
	find . -name *.pyc -delete

%.txt: %.in
	pip-compile $<

requirements-dev.txt: requirements-dev.in
		       dos2unix requirements.txt

${WHEEL}: setup.py git_big/*.py
	python $< bdist_wheel

publish: ${WHEEL}
	git tag ${VERSION}
	git push --tag
	twine upload ${WHEEL}

install:
	pip install -e .

test: install
	pytest
