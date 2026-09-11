import json
import subprocess
from pathlib import Path

import pytest

from roll_qr_scale.weight_limits import validate_production_weights


@pytest.mark.parametrize("machine,limit", [("Máy Bao Bì", 9), ("Máy cách nhiệt", 15.5), ("May cach nhiet", 15.5)])
@pytest.mark.parametrize("unit,factor", [("kg", 1), ("g", 1000), ("lb", 1 / 0.45359237)])
def test_roll_limits_and_boundaries(machine, limit, unit, factor):
    validate_production_weights(1.2 * factor, limit * factor, unit, machine)
    with pytest.raises(ValueError, match="Không cho lưu"):
        validate_production_weights(1 * factor, (limit + .001) * factor, unit, machine)
    with pytest.raises(ValueError, match="lõi giấy"):
        validate_production_weights(1.201 * factor, limit * factor, unit, machine)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_values(value):
    with pytest.raises(ValueError):
        validate_production_weights(value, 9, "kg", "Máy Bao Bì")
    with pytest.raises(ValueError):
        validate_production_weights(1, value, "kg", "Máy Bao Bì")


def test_recycling_roll_has_no_product_limit():
    validate_production_weights(1.2, 100, "kg", "Máy tái chế")


@pytest.mark.parametrize("core,product,machine", [(1.201, 8, "Máy Bao Bì"), (1, 9.001, "Máy Bao Bì"), (1, 15.501, "Máy cách nhiệt")])
def test_capture_rejects_before_saving(tmp_path, core, product, machine):
    import numpy as np
    from roll_qr_scale.storage import MeasurementStore
    from roll_qr_scale.test_ui import StationUIService

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    try:
        with pytest.raises(ValueError, match="Không cho lưu"):
            service.capture("ROLL-001", core, "kg", np.zeros((600, 800, 3), dtype=np.uint8),
                            weight_raw=f"SOURCE_MACHINE={machine}; ERROR_STATUS=error; ERROR_REASON=confirmed",
                            product_weight=product)
        assert store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 0
    finally:
        service.close()
        store.close()


def test_frontend_blocks_overweight_even_with_error_reason_and_images():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    names = ["weightToKg", "productWeightLimitKg", "coreWeightOverLimit", "productWeightOverLimit", "roundOverWeightLimit", "sessionOverWeightLimit", "roundCanSave"]
    script = "const assert=require('node:assert/strict');const CORE_WEIGHT_ALERT_KG=1.2;const PRODUCT_WEIGHT_ALERT_KG=" + json.dumps({"Máy Bao Bì": 9, "Máy cách nhiệt": 15.5}) + ";let sourceContext={machine:'Máy cách nhiệt'};"
    script += "function sessionRoundCount(s){return s.rounds.length}function roundHasDuplicateQr(){return false}function roundQualityReady(){return true}function roundReadyToSave(){return true}"
    script += "\n".join(next(line for line in html.splitlines() if line.startswith("function " + name + "(")) for name in names)
    script += """
const round={weight:1.2,productWeight:15.5,errorStatus:'error',errorReason:'confirmed',coreImage:'image'};
const session={unit:'kg',rounds:[round]};
assert.equal(sessionOverWeightLimit(session),false);
assert.equal(roundCanSave(session,0),true);
round.productWeight=15.501;
assert.equal(sessionOverWeightLimit(session),true);
assert.equal(roundCanSave(session,0),false);
round.productWeight=8;round.weight=1.201;
assert.equal(roundCanSave(session,0),false);
round.weight=1;sourceContext.machine='Máy Bao Bì';round.productWeight=9.001;
assert.equal(roundCanSave(session,0),false);
round.saved=true;assert.equal(sessionOverWeightLimit(session),false);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_frontend_does_not_save_images_when_ai_weight_is_unreadable():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    names = [
        "validWeightValue",
        "roundCoreReady",
        "roundProductReady",
        "roundReadyToSave",
        "roundQualityReady",
        "roundOverWeightLimit",
        "roundCanSave",
    ]
    script = (
        "const assert=require('node:assert/strict');"
        "function roundCode(s,i){return s.rounds[i].qr}"
        "function roundHasDuplicateQr(){return false}"
        "function coreWeightOverLimit(){return false}"
        "function productWeightOverLimit(){return false}"
    )
    script += "\n".join(
        next(line for line in html.splitlines() if line.startswith("function " + name + "("))
        for name in names
    )
    script += """
const round={saved:false,coreImage:'core',productImage:'product',coreAnalysis:{},productAnalysis:{},weight:'',productWeight:'',qr:'ROLL-001',errorStatus:'ok'};
const session={unit:'kg',rounds:[round]};
assert.equal(roundReadyToSave(session,0),false);
assert.equal(roundCanSave(session,0),false);
round.weight='0.16';round.productWeight='1.25';
assert.equal(roundReadyToSave(session,0),true);
assert.equal(roundCanSave(session,0),true);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
