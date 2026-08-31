import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ProjectMenu } from './ProjectMenu'

const projects = [
  { id: 'a', name: 'Alpha' },
  { id: 'b', name: 'Beta' },
]

describe('ProjectMenu', () => {
  it('switches project and confirms delete', async () => {
    const onSwitch = vi.fn()
    const onDelete = vi.fn()
    render(
      <ProjectMenu
        projects={projects}
        currentProjectId="a"
        onCreateSession={vi.fn()}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onDelete={onDelete}
        onSwitch={onSwitch}
      />,
    )

    await userEvent.selectOptions(screen.getByRole('combobox'), 'b')
    expect(onSwitch).toHaveBeenCalledWith('b')

    await userEvent.click(screen.getByRole('button', { name: '项目菜单' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '删除' }))
    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(onDelete).toHaveBeenCalledWith()
  })
})
