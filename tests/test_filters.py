"""Run the browser's filtering logic against a small paper set."""
import pathlib
import subprocess


def test_category_filter_intersections():
    page = pathlib.Path('templates/index.html').read_text()
    script = page.split('<script>')[1].split('initTheme();\nstoreSaved();')[0]
    setup = '''
const assert = require('node:assert/strict');
const element = {textContent:'', value:'', replaceChildren(){}, append(){}, setAttribute(){}, addEventListener(){}, style:{}};
global.document = {getElementById(){return element;}, createElement(){return {...element};}};
global.localStorage = {getItem(){return null;}};
global.getComputedStyle = () => ({getPropertyValue(){return '#fff';}});
let update;
global.Plotly = {restyle(p, data){update = data;}};
'''
    checks = '''
D = {x:[0,1,2,3], c:[0,0,1,1], site:[0,1,2,1], dec:[0,0,1,1], sites:['','Atlanta','Paris'], decisions:['oral','poster']};
sizes = [5,5,5,5];
refreshHighlight();
assert.equal(update.selectedpoints[0], null);
selectedSites.add('Atlanta'); selectedSites.add('Paris');
refreshHighlight();
assert.deepEqual(update.selectedpoints[0], [1,2,3]);
selectedDecisions.add('oral');
refreshHighlight();
assert.deepEqual(update.selectedpoints[0], [1]);
matchSet = new Set([2,3]);
refreshHighlight();
assert.deepEqual(update.selectedpoints[0], []);
matchSet = null; selectedSites.clear(); selectedSites.add('');
refreshHighlight();
assert.deepEqual(update.selectedpoints[0], [0]);
selectedSites.clear(); selectedDecisions.clear(); activeCluster = 1;
refreshHighlight();
assert.deepEqual(update.selectedpoints[0], [2,3]);
'''
    subprocess.run(['node', '-e', setup + script + checks], check=True, capture_output=True, text=True)
