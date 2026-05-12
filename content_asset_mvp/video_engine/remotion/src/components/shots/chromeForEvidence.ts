// Shared chrome resolver for shot templates.
//
// Shot templates used to hard-code the terminal/browser/jupyter chrome
// around the evidence image. That worked when every candidate was a
// GitHub repo, but YouTube candidates now push video keyframes into the
// same shot slots — wrapping a talking-head in a `github.com/repo`
// browser bar looks absurd and breaks the "we're watching a demo" fiction.
//
// This helper looks at `evidence.role` first and only falls back to the
// shot's preset when the role doesn't carry its own source-type signal.

export type ChromeKind = 'terminal' | 'browser' | 'jupyter';

export type ChromeResolution = {
  kind: ChromeKind;
  title: string;
  // True when the evidence is a photo-realistic frame (e.g. a YouTube
  // talking-head or a poster card). Shot templates use this to turn off
  // focus-zoom transforms and switch to objectFit: contain so faces
  // don't get sliced off.
  isPhotographic: boolean;
};

export type ChromePreset = {
  kind: ChromeKind;
  title: string;
};

export const resolveChrome = (
  role: string | undefined,
  repoName: string | undefined,
  preset: ChromePreset,
): ChromeResolution => {
  const normalizedRole = role || '';

  if (normalizedRole.startsWith('youtube_')) {
    // www.youtube.com/watch reads as "we're inside a YouTube tab" to any
    // Douyin viewer. Don't try to embed the specific video id in the bar
    // because it (a) isn't threaded through as a prop yet and (b) would
    // be unreadable at this font size anyway.
    return {
      kind: 'browser',
      title: 'www.youtube.com/watch',
      isPhotographic: true,
    };
  }

  // Future: add explicit branches for twitter_*, producthunt_*, etc.
  // For now, let the shot's own preset (terminal / browser / jupyter)
  // describe GitHub-shaped evidence as before.
  return {
    kind: preset.kind,
    title: preset.title,
    isPhotographic: false,
  };
};
