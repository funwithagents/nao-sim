"""The robot boots: run first for each version (tests-e2e/conftest.py moves it there), so a NAOqi
that does not boot fails this test, with the boot's error, and the version's other tests skip."""


def test_the_robot_boots(nao):
    assert nao.running
    assert nao.service("NaoqiSim").isReady()
