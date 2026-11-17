import json,shutil,subprocess
from pathlib import Path
import pytest


def test_native_dimensions_bind_stored_clip_not_seek_or_previous_payload(tmp_path):
    node=shutil.which('node')
    if node is None:pytest.skip('Node is unavailable')
    source=(Path(__file__).parents[1]/'exercise_motion_pkg/wear_exact_mesh.js').read_text()
    start=source.index('    function wearBindClipDimensions(frames) {')
    stop=source.index('\n    }\n',start)+len('\n    }')
    function=source[start:stop]
    script='''let wearDimensionFrames=null,wearStableBodyProportions=null;
const wearStableSegmentLengths=new Map();
const wearLimbs=[["left_hip","left_knee"]];
'''+function+'''
const pose=(scale)=>({joints:{left_hip:[-scale,0,0],right_hip:[scale,0,0],
left_shoulder:[-2*scale,2,0],right_shoulder:[2*scale,2,0],left_knee:[-scale,-3*scale,0],
neck:[0,3,0],head:[0,3+scale,0]}});
const a=[{joints:{}},pose(1),pose(7)],b=[pose(2),pose(9)];
const snapshot=()=>({body:{...wearStableBodyProportions},lengths:Object.fromEntries(wearStableSegmentLengths)});
wearBindClipDimensions(a);const first=snapshot();
// Seeking to a different pose must not change first-valid stored proportions.
wearBindClipDimensions(a);const seek=snapshot();
wearBindClipDimensions(b);const other=snapshot();
wearBindClipDimensions(a);const restored=snapshot();
console.log(JSON.stringify({first,seek,other,restored}));'''
    path=tmp_path/'binding.js';path.write_text(script)
    report=json.loads(subprocess.check_output([node,str(path)],text=True))
    assert report['first']==report['seek']==report['restored']
    assert report['first']['body']=={'hipWidth':2,'shoulderWidth':4}
    assert report['first']['lengths']['neck->head']==1
    assert report['other']['body']=={'hipWidth':4,'shoulderWidth':8}
    assert report['other']['lengths']['left_hip->left_knee']==6
