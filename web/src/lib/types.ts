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
