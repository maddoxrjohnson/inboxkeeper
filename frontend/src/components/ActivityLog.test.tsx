import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ActionBatch } from '../api/client'
import { mockApi } from '../test/mockApi'
import { ActivityLog } from './ActivityLog'

const archived: ActionBatch = {
  id: 1,
  kind: 'archive',
  status: 'applied',
  created_at: new Date().toISOString(),
  undone_at: null,
  applied_count: 47,
  skipped_count: 3,
  total_size: 2 * 1024 ** 2,
  error: null,
  can_undo: true,
}

function renderLog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ActivityLog />
    </QueryClientProvider>,
  )
}

describe('ActivityLog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders nothing before any actions', async () => {
    const fetchMock = mockApi({ 'GET /api/actions': [] })
    const { container } = renderLog()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('describes each action', async () => {
    mockApi({
      'GET /api/actions': [
        archived,
        {
          ...archived,
          id: 2,
          kind: 'trash',
          status: 'undone',
          can_undo: false,
          skipped_count: 0,
        },
      ],
    })
    renderLog()
    expect(await screen.findByText('Archived 47 emails · 2.0 MB · 3 skipped')).toBeInTheDocument()
    expect(screen.getByText('Moved to trash 47 emails · 2.0 MB')).toBeInTheDocument()
    expect(screen.getByText('Undone')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(1)
  })

  it('asks for confirmation before undoing', async () => {
    const undo = vi.fn(() => ({
      ...archived,
      status: 'undone',
      can_undo: false,
    }))
    mockApi({
      'GET /api/actions': [archived],
      'POST /api/actions/1/undo': undo,
    })
    renderLog()

    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(undo).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes, undo' }))
    await vi.waitFor(() => expect(undo).toHaveBeenCalledOnce())
  })

  it('shows why an undo failed', async () => {
    mockApi({
      'GET /api/actions': [{ ...archived, status: 'failed', error: 'quota exceeded' }],
    })
    renderLog()
    expect(await screen.findByText(/Failed partway: quota exceeded/)).toBeInTheDocument()
  })
})
