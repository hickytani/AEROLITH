const STORAGE_KEY = 'aeropkmech.learn-progress.v1';

export function loadLessonProgress(lessonId, storage = globalThis.localStorage) {
  try {
    const progress = JSON.parse(storage.getItem(STORAGE_KEY) || '{}');
    return progress[lessonId] === true;
  } catch {
    return false;
  }
}

export function saveLessonProgress(lessonId, complete, storage = globalThis.localStorage) {
  try {
    const progress = JSON.parse(storage.getItem(STORAGE_KEY) || '{}');
    progress[lessonId] = Boolean(complete);
    storage.setItem(STORAGE_KEY, JSON.stringify(progress));
    return true;
  } catch {
    return false;
  }
}
