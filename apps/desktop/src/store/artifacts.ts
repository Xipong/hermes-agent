import { atom } from 'nanostores'

import { artifactContentHash, type ArtifactDetection, type ArtifactKind, artifactSlug } from '@/lib/artifact-detect'

import { closeArtifactPreviewTabs, openPreview, type PreviewTarget } from './preview'

/**
 * ARTIFACT REGISTRY — substantial generated content (HTML pages, large SVGs,
 * long code) produced in the transcript, promoted out of the message flow into
 * versioned content the right rail can preview. The registry is authoritative
 * for artifact content; a rail tab only ever holds a reference to it, so a new
 * version shows up in an already-open tab.
 *
 * Identity: one artifact = one (session, slug) pair, where the slug derives
 * from kind + language + title. When the model regenerates "the dashboard"
 * three times in a session, that is ONE artifact with three versions, exactly
 * like a document the user keeps refining — not three cards.
 *
 * Memory-only: the transcript is the durable copy. Cards re-register as they
 * render, so a reload rebuilds the registry (and its version history) for free
 * instead of parking megabytes of generated HTML in localStorage.
 */

export interface ArtifactVersion {
  content: string
  createdAt: number
  hash: string
}

export interface ArtifactRecord {
  createdAt: number
  id: string
  kind: ArtifactKind
  language: string
  sessionId: string
  slug: string
  title: string
  updatedAt: number
  /** Oldest → newest. The last entry is the current version. */
  versions: ArtifactVersion[]
}

export type ArtifactRegistry = Record<string, ArtifactRecord[]>

const MAX_ARTIFACTS_PER_SESSION = 24
const MAX_VERSIONS_PER_ARTIFACT = 20
const MAX_SESSIONS = 40
/**
 * Cumulative generated-source characters retained in addition to the durable
 * transcript. JS strings are UTF-16, so this caps ordinary backing storage at
 * roughly 8 MiB before small object/array overhead. A single newest artifact
 * may exceed the cap: exact executable/renderable content is never truncated.
 */
export const ARTIFACT_REGISTRY_MAX_CONTENT_CHARS = 4 * 1024 * 1024

function artifactRecordContentChars(record: ArtifactRecord): number {
  return record.versions.reduce((total, version) => total + version.content.length, 0)
}

function countBoundedRegistry(registry: ArtifactRegistry): ArtifactRegistry {
  const entries = Object.entries(registry)
    .map(([sessionId, records]) => {
      const trimmed = [...records]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_ARTIFACTS_PER_SESSION)
        .sort((a, b) => a.createdAt - b.createdAt)

      return [sessionId, trimmed] as const
    })
    .filter(([, records]) => records.length > 0)
    .sort(([, a], [, b]) => {
      const latest = (records: readonly ArtifactRecord[]) => Math.max(...records.map(record => record.updatedAt))

      return latest(b) - latest(a)
    })
    .slice(0, MAX_SESSIONS)

  return Object.fromEntries(entries)
}

/**
 * Apply count bounds, then shed duplicate artifact payload by age. Historical
 * versions go first; if latest-only records are still over budget, whole old
 * artifacts go next. Keep one newest record even when its exact current body is
 * itself larger than the budget — silently truncating HTML/code would corrupt it.
 */
function pruneRegistry(registry: ArtifactRegistry): ArtifactRegistry {
  const counted = countBoundedRegistry(registry)
  let totalChars = Object.values(counted)
    .flat()
    .reduce((total, record) => total + artifactRecordContentChars(record), 0)

  if (totalChars <= ARTIFACT_REGISTRY_MAX_CONTENT_CHARS) {
    return counted
  }

  // Work on fresh records/version arrays: callers may still hold the previous
  // atom value, and pruning it in place would mutate React's current snapshot.
  const working = Object.fromEntries(
    Object.entries(counted).map(([sessionId, records]) => [
      sessionId,
      records.map(record => ({ ...record, versions: [...record.versions] }))
    ])
  ) as ArtifactRegistry
  const records = Object.values(working).flat()
  const historical = records
    .flatMap(record =>
      record.versions.slice(0, -1).map(version => ({
        createdAt: version.createdAt,
        hash: version.hash,
        record
      }))
    )
    .sort((a, b) => a.createdAt - b.createdAt)

  for (const candidate of historical) {
    if (totalChars <= ARTIFACT_REGISTRY_MAX_CONTENT_CHARS) {
      break
    }

    const index = candidate.record.versions.findIndex(version => version.hash === candidate.hash)

    if (index === -1 || index === candidate.record.versions.length - 1) {
      continue
    }

    totalChars -= candidate.record.versions[index].content.length
    candidate.record.versions.splice(index, 1)
  }

  let recordCount = records.length
  const oldestRecords = [...records].sort((a, b) => a.updatedAt - b.updatedAt)

  for (const record of oldestRecords) {
    if (totalChars <= ARTIFACT_REGISTRY_MAX_CONTENT_CHARS || recordCount <= 1) {
      break
    }

    const sessionRecords = working[record.sessionId]
    const index = sessionRecords?.findIndex(candidate => candidate.id === record.id) ?? -1

    if (index === -1) {
      continue
    }

    totalChars -= artifactRecordContentChars(sessionRecords[index])
    sessionRecords.splice(index, 1)
    recordCount--

    if (sessionRecords.length === 0) {
      delete working[record.sessionId]
    }
  }

  return working
}

export const $artifactRegistry = atom<ArtifactRegistry>({})

/** Per-artifact selected version index; absent = newest. */
export const $artifactVersionSelection = atom<Record<string, number>>({})

/** Lookup against a registry value, for components that already subscribe to
 *  the atom and need the record to change identity when it does. */
export function findArtifact(registry: ArtifactRegistry, artifactId: string): ArtifactRecord | null {
  for (const records of Object.values(registry)) {
    const found = records.find(record => record.id === artifactId)

    if (found) {
      return found
    }
  }

  return null
}

function sameVersionSelection(a: Record<string, number>, b: Record<string, number>): boolean {
  const aEntries = Object.entries(a)
  const bEntries = Object.entries(b)

  return aEntries.length === bEntries.length && aEntries.every(([id, index]) => b[id] === index)
}

/** Keep a pinned surviving version attached to its content hash when pruning
 * removes older array entries. Missing/pruned pins fall back to newest. */
function reconcileVersionSelection(previous: ArtifactRegistry, next: ArtifactRegistry): void {
  const selection = $artifactVersionSelection.get()

  if (Object.keys(selection).length === 0) {
    return
  }

  const reconciled: Record<string, number> = {}

  for (const [artifactId, selectedIndex] of Object.entries(selection)) {
    const selectedHash = findArtifact(previous, artifactId)?.versions[selectedIndex]?.hash
    const nextRecord = findArtifact(next, artifactId)

    if (!selectedHash || !nextRecord) {
      continue
    }

    const nextIndex = nextRecord.versions.findIndex(version => version.hash === selectedHash)

    if (nextIndex >= 0 && nextIndex < nextRecord.versions.length - 1) {
      reconciled[artifactId] = nextIndex
    }
  }

  if (!sameVersionSelection(selection, reconciled)) {
    $artifactVersionSelection.set(reconciled)
  }
}

function commitArtifactRegistry(candidate: ArtifactRegistry): ArtifactRegistry {
  const previous = $artifactRegistry.get()
  const next = pruneRegistry(candidate)

  reconcileVersionSelection(previous, next)
  $artifactRegistry.set(next)

  return next
}

export function getArtifact(artifactId: string): ArtifactRecord | null {
  return findArtifact($artifactRegistry.get(), artifactId)
}

export function artifactsForSession(sessionId: string | null | undefined): ArtifactRecord[] {
  const id = sessionId?.trim()

  if (!id) {
    return []
  }

  return $artifactRegistry.get()[id] ?? []
}

interface UpsertResult {
  artifactId: string
  record: ArtifactRecord
  /** True when this call appended a NEW version (vs. deduped/no-op). */
  versionAdded: boolean
}

/**
 * Register (or version) an artifact for a session. Same slug + same content
 * hash is a no-op (streaming remounts and transcript re-renders call this
 * repeatedly); same slug + new content appends a version.
 */
export function upsertArtifact(
  sessionId: string | null | undefined,
  detection: ArtifactDetection,
  content: string
): UpsertResult | null {
  const id = sessionId?.trim()
  const trimmed = content.trim()

  if (!id || !trimmed) {
    return null
  }

  const slug = artifactSlug(detection)
  const hash = artifactContentHash(trimmed)
  const registry = $artifactRegistry.get()
  const records = registry[id] ?? []
  const existing = records.find(record => record.slug === slug)
  const now = Date.now()

  if (existing) {
    const known = existing.versions.some(version => version.hash === hash)

    if (known) {
      return { artifactId: existing.id, record: existing, versionAdded: false }
    }

    const versions = [...existing.versions, { content: trimmed, createdAt: now, hash }].slice(
      -MAX_VERSIONS_PER_ARTIFACT
    )

    const next: ArtifactRecord = {
      ...existing,
      // A regenerated artifact may carry a sharper title (html <title> arrives
      // late in the stream); prefer the newest non-generic one.
      title: detection.title || existing.title,
      updatedAt: now,
      versions
    }

    const committed = commitArtifactRegistry({
      ...registry,
      [id]: records.map(record => (record.id === existing.id ? next : record))
    })
    const committedRecord = findArtifact(committed, existing.id) ?? next

    return { artifactId: existing.id, record: committedRecord, versionAdded: true }
  }

  const record: ArtifactRecord = {
    createdAt: now,
    id: `${id}:${slug}`,
    kind: detection.kind,
    language: detection.language,
    sessionId: id,
    slug,
    title: detection.title,
    updatedAt: now,
    versions: [{ content: trimmed, createdAt: now, hash }]
  }

  const committed = commitArtifactRegistry({ ...registry, [id]: [...records, record] })
  const committedRecord = findArtifact(committed, record.id) ?? record

  return { artifactId: record.id, record: committedRecord, versionAdded: true }
}

/** A rail tab for an artifact references the registry by id rather than
 *  carrying content, so an open tab follows the artifact as it gains versions. */
export function artifactPreviewTarget(record: ArtifactRecord): PreviewTarget {
  return { kind: 'artifact', label: record.title, source: record.id, url: record.id }
}

/** Open an artifact in the right rail at `versionIndex` (default: newest).
 *  User-initiated only (card click) — never called from streaming, per the
 *  no-hijack rule. */
export function openArtifact(artifactId: string, versionIndex?: number) {
  const record = getArtifact(artifactId)

  if (!record) {
    return
  }

  selectArtifactVersion(artifactId, versionIndex ?? record.versions.length - 1)
  openPreview(artifactPreviewTarget(record))
}

export function selectArtifactVersion(artifactId: string, versionIndex: number) {
  const record = getArtifact(artifactId)

  if (!record) {
    return
  }

  const clamped = Math.max(0, Math.min(record.versions.length - 1, versionIndex))
  const selection = $artifactVersionSelection.get()

  if (clamped === record.versions.length - 1) {
    if (artifactId in selection) {
      const { [artifactId]: _dropped, ...rest } = selection
      $artifactVersionSelection.set(rest)
    }

    return
  }

  $artifactVersionSelection.set({ ...selection, [artifactId]: clamped })
}

export function clearArtifactRegistry() {
  $artifactRegistry.set({})
  $artifactVersionSelection.set({})
  closeArtifactPreviewTabs()
}
