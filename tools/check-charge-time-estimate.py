#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run exact production method bodies with controlled metadata and real step averaging."""
from pathlib import Path
import hashlib,json,re,subprocess
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--baseline-source',type=Path)
args=parser.parse_args()
ROOT=args.source_root.resolve();OUT=args.output.resolve();OUT.mkdir(mode=0o700)
new=(ROOT/'frameworks/base/services/core/java/com/android/server/power/stats/BatteryStatsImpl.java').read_text()
old=args.baseline_source.read_text() if args.baseline_source else new.replace('!mPreferChargeStepEstimate && ', '')
framework=(ROOT/'frameworks/base/core/java/android/os/BatteryStats.java').read_text()
def method(s,marker):
 start=s.index(marker);opening=s.index('{',start);depth=0
 for i in range(opening,len(s)):
  if s[i]=='{':depth+=1
  elif s[i]=='}':
   depth-=1
   if depth==0:return s[start:i+1]
 raise AssertionError('Unbalanced method')
mask=re.search(r'public static final long STEP_LEVEL_TIME_MASK\s*=\s*([^;]+);',framework).group(1)
tracker=method(framework,'public long computeTimePerLevel()')
field=re.search(r'private final boolean mPreferChargeStepEstimate\s*=.*?;',new,re.S).group(0)
tests=r'''
    static int checks;
    static void equal(long actual, long wanted, String why) { checks++; if(actual!=wanted) throw new AssertionError(why+": "+actual+" != "+wanted); }
    static Estimate make(Boolean prefer, boolean onBattery, int level, long healthSeconds, long... durations) {
        SystemProperties.config=prefer;
        Estimate estimate=new Estimate();estimate.mOnBattery=onBattery;estimate.mBatteryLevel=level;estimate.mBatteryTimeToFullSeconds=healthSeconds;estimate.mChargeStepTracker=new LevelStepTracker(durations);return estimate;
    }
    public static void main(String[] args) {
        // Exact field values captured while this phone charged 78 -> 82 percent.
        long[] steps={153601,122880,153597,122879,122881};
        equal(make(true,false,82,0,steps).computeChargeTimeRemaining(0),2433006000L,"invalid zero must use observed 82-percent progress");
        equal(make(true,false,82,8*86400,steps).computeChargeTimeRemaining(0),2433006000L,"unreliable eight-day health input must not override actual progress");
        equal(make(true,false,82,-1,steps).computeChargeTimeRemaining(0),2433006000L,"unsupported health input uses the same Android fallback");
        equal(make(true,false,82,0).computeChargeTimeRemaining(0),-1L,"no samples stays unknown");
        equal(make(true,false,82,0,0,0).computeChargeTimeRemaining(0),-1L,"zero-duration samples stay unknown");
        equal(make(true,false,100,-1).computeChargeTimeRemaining(0),0L,"full battery remains zero without samples");
        equal(make(true,true,82,0,steps).computeChargeTimeRemaining(0),-1L,"unplugged battery has no charge estimate");
        equal(make(true,false,50,99,60000,120000).computeChargeTimeRemaining(0)/1000,4500000L,"public API conversion remains milliseconds");
        equal(make(false,false,82,0,steps).computeChargeTimeRemaining(0),0L,"other-device health-first behavior unchanged");
        equal(make(false,false,82,8*86400,steps).computeChargeTimeRemaining(0),8L*86400*1000000,"positive health behavior unchanged without opt-in");
        equal(make(null,false,82,0,steps).computeChargeTimeRemaining(0),0L,"absent property preserves the default");
        equal(make(false,false,82,-1,steps).computeChargeTimeRemaining(0),2433006000L,"legacy unsupported path unchanged");
        System.out.println("PASS "+checks+" production-estimator cases; real 82-percent fixture = 2433006 ms");
    }
'''
common=r'''
class SystemProperties {
 static Boolean config;
 static boolean getBoolean(String name, boolean fallback) {
  if (!"ro.config.prefer_charge_step_estimate".equals(name) || fallback) throw new AssertionError("Device property contract changed");
  return config==null?fallback:config;
 }
}
class LevelStepTracker {
 static final long STEP_LEVEL_TIME_MASK=MASK;
 final long[] mStepDurations;final int mNumStepDurations;
 LevelStepTracker(long... durations){mStepDurations=durations;mNumStepDurations=durations.length;}
 TRACKER
}
class Estimate {
 boolean mOnBattery;int mBatteryLevel;long mBatteryTimeToFullSeconds;LevelStepTracker mChargeStepTracker;
 FIELD
 METHOD
}
public class EstimatorTest {
 TESTS
}
'''.replace('=MASK;', '='+mask+';').replace(' TRACKER',tracker).replace(' FIELD',field).replace(' TESTS',tests)
java=ROOT/'prebuilts/jdk/jdk21/linux-x86/bin';records=[]
for name,text,expected in [('before',old,1),('after',new,0)]:
 d=OUT/name;d.mkdir();production=method(text,'public long computeChargeTimeRemaining(long curTime)')
 (d/'EstimatorTest.java').write_text(common.replace(' METHOD',production))
 p=subprocess.run([str(java/'javac'),'--release','17',str(d/'EstimatorTest.java')],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([str(java/'java'),'-Xmx96m','-cp',str(d),'EstimatorTest'],capture_output=True,text=True);(d/'result.log').write_text(p.stdout+p.stderr)
 assert p.returncode==expected,p.stdout+p.stderr
 records.append({'name':name,'exit_code':p.returncode,'production_method_sha256':hashlib.sha256(production.encode()).hexdigest()})
 print(name,p.returncode,(p.stdout+p.stderr).splitlines()[0])
report={'status':'production-estimator-regression-and-negative-baseline-passed','records':records,'actual_fixture_expected_milliseconds':2433006,'phone_operations':False};(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
