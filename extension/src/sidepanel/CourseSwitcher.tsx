import type { SavedCourse } from "../shared/types";

interface Props {
  courses: SavedCourse[];
  activeCourseId: string | null;
  pageExternalId: string | null;
  onSelect: (courseId: string) => void;
}

function shortName(name: string): string {
  if (name.length <= 42) return name;
  return name.slice(0, 40) + "…";
}

export function CourseSwitcher({ courses, activeCourseId, pageExternalId, onSelect }: Props) {
  if (courses.length === 0) {
    return (
      <div className="course-switcher empty">
        <p className="switcher-title">我的课程</p>
        <p className="switcher-empty">还没有同步过的课程</p>
      </div>
    );
  }

  return (
    <div className="course-switcher">
      <p className="switcher-title">我的课程</p>
      <div className="course-list">
        {courses.map((course) => {
          const isActive = course.courseId === activeCourseId;
          const onCurrentPage = pageExternalId === course.externalId;
          return (
            <button
              key={course.courseId}
              type="button"
              className={`course-item ${isActive ? "active" : ""}`}
              onClick={() => onSelect(course.courseId)}
            >
              <div className="course-item-head">
                <span className="course-dot">{isActive ? "●" : "○"}</span>
                <span className="course-item-name">{shortName(course.name)}</span>
                {onCurrentPage && !isActive && (
                  <span className="course-badge">当前页</span>
                )}
                {isActive && (
                  <span className="course-badge asking">提问中</span>
                )}
              </div>
              <div className="course-item-meta">
                {course.topicCount} 文件 · {course.chunkCount} 段
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
