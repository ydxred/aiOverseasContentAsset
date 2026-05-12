import React from 'react';
import {ImpactTitleShot} from './ImpactTitleShot';
import {KeywordPunchShot} from './KeywordPunchShot';
import {JudgementShot} from './JudgementShot';
import {RepoFullBleedShot} from './RepoFullBleedShot';
import {RepoEvidenceZoomShot} from './RepoEvidenceZoomShot';
import {BrowserFocusShot} from './BrowserFocusShot';
import {ReadmeVisualCardShot} from './ReadmeVisualCardShot';
import type {ShotTemplateProps} from './types';

const TEMPLATES: Record<string, React.FC<ShotTemplateProps>> = {
  impact_title_card: ImpactTitleShot,
  keyword_punch_card: KeywordPunchShot,
  judgement_card: JudgementShot,
  story_beat_card: KeywordPunchShot,
  signal_pulse_card: KeywordPunchShot,
  repo_full_bleed: RepoFullBleedShot,
  repo_evidence_zoom: RepoEvidenceZoomShot,
  readme_visual_card: ReadmeVisualCardShot
};

export const ShotDispatcher: React.FC<ShotTemplateProps> = (props) => {
  const visualType = props.shot?.visual_type || '';
  const role = props.evidence?.role || '';
  if (TEMPLATES[visualType]) {
    const Template = TEMPLATES[visualType];
    return <Template {...props} />;
  }
  if (role.startsWith('browser_')) {
    return <BrowserFocusShot {...props} />;
  }
  return <BrowserFocusShot {...props} />;
};
