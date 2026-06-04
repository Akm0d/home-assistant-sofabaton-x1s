import type { BackupBundleActivityPayload, BackupBundleDevicePayload, BackupBundlePayload, CacheHubState } from "../shared/ha-context";
import { BACKUP_BUNDLE_SCHEMA_VERSION } from "../shared/ha-context";
import { hubActivities, hubDevices } from "../shared/utils/control-panel-selectors";

export interface BackupSelectionOption {
  id: number;
  label: string;
  meta?: string;
}

export interface RestoreSelectionState {
  forcedDeviceIds: number[];
  selectedDeviceIds: number[];
}

const HUB_VERSION_RANK: Record<string, number> = {
  X1: 1,
  X1S: 2,
  X2: 3,
};

export function backupActivityOptions(hub: CacheHubState | null): BackupSelectionOption[] {
  return hubActivities(hub).map((activity) => ({
    id: Number(activity.id),
    label: String(activity.name || `Activity ${activity.id}`),
    meta: `${Number(activity.favorite_count || 0)} favs · ${Number(activity.macro_count || 0)} macros`,
  }));
}

export function backupDeviceOptions(hub: CacheHubState | null): BackupSelectionOption[] {
  return hubDevices(hub).map((device) => ({
    id: Number(device.id),
    label: String(device.name || `Device ${device.id}`),
    meta: String(device.device_class || "").trim() || undefined,
  }));
}

export function bundleActivityOptions(bundle: BackupBundlePayload | null): BackupSelectionOption[] {
  return [...(bundle?.activities ?? [])]
    .map((activity) => {
      const block = activity?.device || {};
      const id = Number(block.device_id || 0);
      return {
        id,
        label: String(block.name || `Activity ${id}`),
        meta: `${(activity?.referenced_source_device_ids ?? []).length} linked devices`,
      };
    })
    .filter((option) => option.id > 0)
    .sort((left, right) => left.label.localeCompare(right.label));
}

export function bundleDeviceOptions(bundle: BackupBundlePayload | null): BackupSelectionOption[] {
  return [...(bundle?.devices ?? [])]
    .map((device) => {
      const block = device?.device || {};
      const id = Number(block.device_id || 0);
      return {
        id,
        label: String(block.name || `Device ${id}`),
        meta: String(block.device_class || "").trim() || undefined,
      };
    })
    .filter((option) => option.id > 0)
    .sort((left, right) => left.label.localeCompare(right.label));
}

export function forcedRestoreDeviceIds(bundle: BackupBundlePayload | null, selectedActivityIds: number[]): number[] {
  const selected = new Set(selectedActivityIds.map((value) => Number(value)));
  const forced = new Set<number>();
  for (const activity of bundle?.activities ?? []) {
    const activityId = Number(activity?.device?.device_id || 0);
    if (!selected.has(activityId)) continue;
    for (const deviceId of activity?.referenced_source_device_ids ?? []) {
      const normalized = Number(deviceId);
      if (normalized > 0) forced.add(normalized);
    }
  }
  return [...forced].sort((left, right) => left - right);
}

export function reconcileRestoreSelection(params: {
  bundle: BackupBundlePayload | null;
  selectedActivityIds: number[];
  manualSelectedDeviceIds: number[];
}): RestoreSelectionState {
  const forcedDeviceIds = forcedRestoreDeviceIds(params.bundle, params.selectedActivityIds);
  const selected = new Set<number>(forcedDeviceIds);
  for (const deviceId of params.manualSelectedDeviceIds ?? []) {
    const normalized = Number(deviceId);
    if (normalized > 0) selected.add(normalized);
  }
  return {
    forcedDeviceIds,
    selectedDeviceIds: [...selected].sort((left, right) => left - right),
  };
}

export function backupUsesWholeHub(selectedActivityIds: number[]): boolean {
  return (selectedActivityIds ?? []).length > 0;
}

export function pruneBackupBundle(params: {
  bundle: BackupBundlePayload;
  selectedActivityIds: number[];
  selectedDeviceIds: number[];
}): BackupBundlePayload {
  const selectedActivityIds = new Set((params.selectedActivityIds ?? []).map((value) => Number(value)));
  const selectedDeviceIds = new Set((params.selectedDeviceIds ?? []).map((value) => Number(value)));
  return {
    ...params.bundle,
    devices: (params.bundle.devices ?? []).filter((device) => selectedDeviceIds.has(Number(device?.device?.device_id || 0))),
    activities: (params.bundle.activities ?? []).filter((activity) => selectedActivityIds.has(Number(activity?.device?.device_id || 0))),
  };
}

export function validateBackupBundle(raw: unknown): BackupBundlePayload {
  if (!raw || typeof raw !== "object") {
    throw new Error("Backup file must contain a JSON object.");
  }
  const bundle = raw as BackupBundlePayload;
  if (String(bundle.kind || "") !== "hub_bundle") {
    throw new Error("Backup file is not a Sofabaton hub bundle.");
  }
  if (Number(bundle.schema_version || 0) !== BACKUP_BUNDLE_SCHEMA_VERSION) {
    throw new Error(
      `Backup file schema_version must be ${BACKUP_BUNDLE_SCHEMA_VERSION} (got ${String(bundle.schema_version || "") || "unknown"}).`,
    );
  }
  if (!Array.isArray(bundle.devices) || !Array.isArray(bundle.activities)) {
    throw new Error("Backup file is missing devices or activities arrays.");
  }
  return bundle;
}

export function normalizeHubVersion(value: unknown): string | null {
  const normalized = String(value ?? "").trim().toUpperCase();
  if (!normalized) return null;
  if (normalized.includes("X1S")) return "X1S";
  if (normalized.includes("X2")) return "X2";
  if (normalized.includes("X1")) return "X1";
  return null;
}

export function renameBundleHub(bundle: BackupBundlePayload, name: string): BackupBundlePayload {
  const trimmed = String(name ?? "").trim();
  if (!trimmed) return bundle;
  return {
    ...bundle,
    hub: { ...(bundle.hub ?? {}), name: trimmed },
  };
}

function renameInList<T extends { device?: BackupBundleDeviceBlock | null }>(
  list: T[] | undefined,
  id: number,
  name: string,
): T[] {
  const trimmed = String(name ?? "").trim();
  return (list ?? []).map((entry) => {
    const block = entry?.device;
    if (!block || Number(block.device_id || 0) !== id) return entry;
    return { ...entry, device: { ...block, name: trimmed || block.name || `Device ${id}` } };
  });
}

export function renameBundleActivity(
  bundle: BackupBundlePayload,
  activityId: number,
  name: string,
): BackupBundlePayload {
  return { ...bundle, activities: renameInList(bundle.activities, Number(activityId), name) };
}

export function renameBundleDevice(
  bundle: BackupBundlePayload,
  deviceId: number,
  name: string,
): BackupBundlePayload {
  return { ...bundle, devices: renameInList(bundle.devices, Number(deviceId), name) };
}

export function assertBackupBundleRestoreCompatible(bundle: BackupBundlePayload, destinationHubVersion: unknown) {
  const sourceVersion = normalizeHubVersion(bundle?.hub?.version);
  if (!sourceVersion) {
    throw new Error("Backup file is missing its source hub model, so compatibility cannot be verified.");
  }
  const destinationVersion = normalizeHubVersion(destinationHubVersion);
  if (!destinationVersion) {
    throw new Error("The destination hub model is unknown, so restore compatibility cannot be verified.");
  }
  if (HUB_VERSION_RANK[destinationVersion] < HUB_VERSION_RANK[sourceVersion]) {
    throw new Error(
      `This backup was created on a Sofabaton ${sourceVersion} hub and cannot be restored onto a Sofabaton ${destinationVersion} hub.`,
    );
  }
}
