export interface LessonStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}
export function loadLessonProgress(lessonId: string, storage?: LessonStorage): boolean;
export function saveLessonProgress(lessonId: string, complete: boolean, storage?: LessonStorage): boolean;
