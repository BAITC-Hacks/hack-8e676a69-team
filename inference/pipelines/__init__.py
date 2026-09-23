import test from pipelines.test

pipelines = {
	'test': Test()
}
from .test import Test


def build_pipelines():
    return {"test": Test()}
