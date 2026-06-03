export type User = {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
};

export type Device = {
  id: number;
  device_key: string;
  name: string;
  location: string | null;
  last_seen_at: string | null;
};

export type Reading = {
  time: string;
  temperature: number;
  lux: number;
  battery_raw: number | null;
  battery_v: number | null;
  rssi: number | null;
};

export type DeviceWithLatestReading = {
  device: Device;
  latest: Reading | null;
};

export type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d';

// ---------- Admin types ----------

export type UserAdmin = {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  has_password: boolean;
  device_count: number;
};

export type DeviceForUser = {
  id: number;
  device_key: string;
  name: string;
  location: string | null;
  created_at: string;
  last_seen_at: string | null;
  mqtt_provisioned: boolean;
};

export type UserAdminDetail = UserAdmin & {
  devices: DeviceForUser[];
};

export type Owner = {
  id: number;
  email: string;
  display_name: string;
};

export type DeviceAdmin = {
  id: number;
  device_key: string;
  name: string;
  location: string | null;
  created_at: string;
  last_seen_at: string | null;
  mqtt_provisioned: boolean;
  owner: Owner;
};

export type CreateUserResponse = {
  user: UserAdmin;
  invitation_url: string;
};

export type ResetLinkResponse = {
  reset_url: string;
};

export type InvitationLinkResponse = {
  invitation_url: string;
};

export type CreateDeviceResponse = {
  device: DeviceAdmin;
  mqtt_password: string;
  ssh_command: string;
};

export type RotateMqttResponse = {
  mqtt_password: string;
  ssh_command: string;
};

export type DeviceStatus = 'online' | 'offline';

export type DevicePatch = Partial<{
  name: string;
  location: string | null;
  user_id: number;
  mqtt_provisioned: boolean;
}>;
