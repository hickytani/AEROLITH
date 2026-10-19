'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import ProductHeader from '../components/ProductHeader';
import { loadLessonProgress, saveLessonProgress } from '../lib/learning.mjs';

type Parameters = {
  pinion_teeth: number; gear_teeth: number; module_mm: number; face_width_mm: number;
  input_torque_Nm: number; input_speed_rpm: number;
};
type Experiment = { derived: Record<string, number | string>; calculations: { provenance: { source_revision: number }; results: Array<{ key: string; name: string; value: number; unit: string; formula: string; substitution: string; assumptions: string[] }> } };

const initial: Parameters = { pinion_teeth: 18, gear_teeth: 54, module_mm: 2, face_width_mm: 12, input_torque_Nm: 8, input_speed_rpm: 900 };
const areas = [
  ['Mechanical systems', 'Planned', 'No connected lesson yet.'],
  ['Gears and transmissions', 'Available', 'Interactive lesson: ratio, pitch geometry, and ideal kinematics.'],
  ['Motors and electromechanical systems', 'Planned', 'No motor model is implemented.'],
  ['Aerospace fundamentals and aerodynamics', 'Planned', 'No aircraft or aerodynamic design family is implemented.'],
  ['Robotics and mechanisms', 'Planned', 'No joint, linkage, or robot model is implemented.'],
  ['CAD fundamentals', 'Planned', 'The current CAD output is a constrained educational gear example.'],
];

export default function LearnPage() {
  const [parameters, setParameters] = useState(initial);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [experimentError, setExperimentError] = useState('');
  const [quizAnswer, setQuizAnswer] = useState('');
  const [complete, setComplete] = useState(false);
  const [apiLoading, setApiLoading] = useState(true);

  useEffect(() => { setComplete(loadLessonProgress('spur-gear-ratio')); }, []);
  useEffect(() => {
    const timer = window.setTimeout(async () => {
      setApiLoading(true);
      try {
        const response = await fetch('/api/v1/learn/spur-gear/experiment', {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(parameters),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the highlighted parameter ranges.');
        setExperiment(data);
        setExperimentError('');
      } catch (error) {
        setExperimentError(error instanceof Error ? error.message : 'Calculation service is unavailable.');
      } finally { setApiLoading(false); }
    }, 180);
    return () => window.clearTimeout(timer);
  }, [parameters]);

  const byKey = useMemo(() => new Map((experiment?.calculations.results || []).map((item) => [item.key, item])), [experiment]);
  function change<K extends keyof Parameters>(key: K, value: string) {
    setParameters((current) => ({ ...current, [key]: value === '' ? 0 : Number(value) }));
  }
  function markComplete() {
    const next = !complete;
    setComplete(next);
    saveLessonProgress('spur-gear-ratio', next);
  }

  return <><ProductHeader active="learn"/><main className="product-main learn-page">
    <p className="eyebrow">AEROPKMECH LEARN / MECHANICAL SYSTEMS</p>
    <div className="product-title-row"><div><h1>Gears and transmissions</h1><p className="sub">Lesson 01 · Follow a real spur-gear project through the equations that drive its results.</p></div><Link className="button-link" href="/">Open Studio design ↗</Link></div>
    <div className="learn-layout">
      <aside className="learning-nav"><h2>Learning areas</h2>{areas.map(([name, state, description]) => <section key={name} className={state === 'Available' ? 'topic available' : 'topic'}><span>{state}</span><strong>{name}</strong><p>{description}</p></section>)}<div className="local-progress"><strong>Lesson progress</strong><p>{complete ? 'Completed in this browser' : 'Not completed'}</p><small>Stored locally on this browser. No account or cross-device sync.</small></div></aside>
      <article className="lesson">
        <section className="lesson-section"><p className="eyebrow">01 / START WITH TOOTH COUNTS</p><h2>Why does a gear ratio change speed?</h2><p>At the reference circles of an ordinary external gear pair, the tangential speeds match. The tooth counts set the pitch diameters, so their ratio sets the ideal speed ratio. The driven gear turns in the opposite direction; these values show speed magnitude.</p>
          <div className="equation">i = z₂ / z₁ <span>· ratio from driven teeth over pinion teeth</span></div>
          <div className="experiment-grid">
            <label>Pinion teeth<input type="number" min="8" max="80" value={parameters.pinion_teeth} onChange={(event) => change('pinion_teeth', event.target.value)}/></label>
            <label>Driven gear teeth<input type="number" min="8" max="120" value={parameters.gear_teeth} onChange={(event) => change('gear_teeth', event.target.value)}/></label>
            <label>Module<input type="number" min="0.5" max="6" step="0.1" value={parameters.module_mm} onChange={(event) => change('module_mm', event.target.value)}/><small>mm</small></label>
            <label>Face width<input type="number" min="2" max="60" step="1" value={parameters.face_width_mm} onChange={(event) => change('face_width_mm', event.target.value)}/><small>mm</small></label>
            <label>Input torque<input type="number" min="0.1" step="0.1" value={parameters.input_torque_Nm} onChange={(event) => change('input_torque_Nm', event.target.value)}/><small>N·m</small></label>
            <label>Input speed<input type="number" min="1" step="10" value={parameters.input_speed_rpm} onChange={(event) => change('input_speed_rpm', event.target.value)}/><small>rpm</small></label>
          </div>
          <div className="experiment-results" aria-live="polite"><div><small>TRANSMISSION RATIO</small><strong>{Number(experiment?.derived.gear_ratio || 0).toFixed(2)}:1</strong></div><div><small>CENTER DISTANCE</small><strong>{Number(experiment?.derived.center_distance_mm || 0).toFixed(2)} mm</strong></div><div><small>IDEAL OUTPUT SPEED</small><strong>{Number(experiment?.derived.output_speed_rpm || 0).toFixed(2)} rpm</strong></div><div><small>IDEAL OUTPUT TORQUE</small><strong>{Number(experiment?.derived.ideal_output_torque_Nm || 0).toFixed(2)} N·m</strong></div></div>
          {apiLoading && <p className="inline-status">Calculating with the Studio engineering core…</p>}{experimentError && <p className="inline-error" role="alert">{experimentError}</p>}
          {experiment && <p className="provenance">Calculated by {experiment.calculations.results[0]?.key ? 'spur-gear-kinematics-0.1' : 'the gear model'} · uncommitted experiment · source project revision {experiment.calculations.provenance.source_revision}.</p>}
        </section>
        <section className="lesson-section"><p className="eyebrow">02 / READ THE GEOMETRY</p><h2>Module sets the pitch scale</h2><p>For an ordinary unshifted spur pair, pitch diameter is module times tooth count. The center distance is half the sum of those diameters. Increasing module scales both diameters and center distance; changing tooth counts changes the ratio and the corresponding pitch circles.</p>
          <div className="worked-example"><strong>Current experiment</strong><p>{byKey.get('pinion_pitch_diameter_mm')?.formula} = {byKey.get('pinion_pitch_diameter_mm')?.substitution} = {Number(experiment?.derived.pinion_pitch_diameter_mm || 0).toFixed(2)} mm pinion pitch diameter.</p><p>{byKey.get('center_distance_mm')?.formula} = {byKey.get('center_distance_mm')?.substitution} = {Number(experiment?.derived.center_distance_mm || 0).toFixed(2)} mm center distance.</p></div>
          <p>These equations describe standard reference dimensions. The current CAD uses four vertices per tooth in a polygonal approximation, not a conjugate involute tooth profile. The displayed nominal tip diameter is not necessarily the model’s axis-aligned bounding-box width.</p>
        </section>
        <section className="lesson-section"><p className="eyebrow">03 / IDEAL KINEMATICS</p><h2>Speed trades against torque in the ideal model</h2><p>The lesson assumes a lossless transmission: power in equals power out. With angular speed proportional to rotational speed, torque scales by the ratio while speed scales inversely. Real efficiency, forces, stress and service conditions are not modeled.</p><div className="equation">n₂ = n₁ / i <span>and</span> T₂ = T₁ × i</div><p>For the default 18/54 pair, 900 rpm / 3 = 300 rpm and 8 N·m × 3 = 24 N·m ideal output torque. This result is not a gear load rating.</p></section>
        <section className="lesson-section quiz"><p className="eyebrow">04 / CHECK YOUR UNDERSTANDING</p><h2>Try a prediction</h2><p>If the driven gear changes from 54 to 30 teeth while the pinion stays at 12 teeth, what happens to the ratio and center distance at module 2 mm?</p>
          <label><input type="radio" name="quiz" value="answer" checked={quizAnswer === 'answer'} onChange={() => setQuizAnswer('answer')}/> Ratio becomes 2.5:1 and center distance is 42 mm.</label>
          <label><input type="radio" name="quiz" value="wrong" checked={quizAnswer === 'wrong'} onChange={() => setQuizAnswer('wrong')}/> Ratio stays 3:1 and center distance stays 72 mm.</label>
          {quizAnswer && <p className={quizAnswer === 'answer' ? 'quiz-feedback correct' : 'quiz-feedback'}>{quizAnswer === 'answer' ? 'Correct. i = 30/12 = 2.5 and a = 2(12+30)/2 = 42 mm. The same inputs in Studio produce 360 rpm and 20 N·m ideal output.' : 'Not quite. Use the new driven tooth count in both equations: i = z₂/z₁, and a = m(z₁+z₂)/2.'}</p>}
        </section>
        <section className="lesson-section limits"><p className="eyebrow">MODEL LIMITS</p><h2>What this lesson cannot verify</h2><p>Tooth strength, contact stress, interference, backlash, fatigue life, temperature, lubrication, manufacturing tolerances, and safety are unknown or untested. No material or acceptance criteria are supplied. A valid CAD solid and a numerical result do not establish that a real transmission is safe or manufacturable.</p><Link className="text-link" href="/">Open the corresponding Studio design →</Link></section>
        <button className="primary completion-button" onClick={markComplete}>{complete ? 'Mark lesson incomplete' : 'Mark lesson complete'}</button>
      </article>
    </div>
  </main></>;
}
