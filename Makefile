.PHONY: all clean test publish

VERSION=$(shell python -c 'import git_big; print(git_big.__version__)')

WHEEL=dist/git_big-${VERSION}-py2-none-any.whl

all: requirements-dev.txt ${WHEEL}
clean:
	rm -f requirements*.txt
	rm -rf build
	rm -rf dist

%.txt: %.in
	pip-compile $<

requirements-dev.txt: requirements-dev.in

${WHEEL}: setup.py git_big/*.py
	python $< bdist_wheel

publish: ${WHEEL}
	twine upload ${WHEEL}

test:
	nosetests
