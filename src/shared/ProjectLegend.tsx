import { projectColor } from './projectColors'
import type { Project } from './types'

export function ProjectLegend({ projects }: { projects: Project[] }) {
  return (
    <div className="project-legend">
      {projects.map((project) => (
        <span key={project.id}>
          <i style={{ backgroundColor: projectColor(project.id) }} />
          {project.title}
        </span>
      ))}
    </div>
  )
}
