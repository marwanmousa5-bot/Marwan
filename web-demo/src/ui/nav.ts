import type { ComponentType } from 'react';
import {
  IconAlert, IconChart, IconCoin, IconDispatch, IconDoc, IconFuel, IconHistory,
  IconIncident, IconLeaf, IconMap, IconSettings, IconShield, IconSpark, IconTasks,
  IconTruck, IconUsers, IconWrench, IconZone,
} from './icons';

export interface NavItem {
  key: string;
  label: string;
  icon: ComponentType<{ size?: number }>;
  purpose: string;
  group: string;
}

/** The customer-facing information architecture, in operational order. */
export const NAV: NavItem[] = [
  { key: 'live', label: 'Live Tracking', icon: IconMap, group: 'Operate',
    purpose: 'What is happening now?' },
  { key: 'alerts', label: 'Alerts', icon: IconAlert, group: 'Operate',
    purpose: 'What needs attention?' },
  { key: 'dispatch', label: 'Dispatch', icon: IconDispatch, group: 'Operate',
    purpose: 'Who should handle it?' },
  { key: 'tasks', label: 'Tasks', icon: IconTasks, group: 'Operate',
    purpose: 'What needs to be done?' },

  { key: 'vehicles', label: 'Vehicles', icon: IconTruck, group: 'Fleet',
    purpose: 'What assets do we have?' },
  { key: 'drivers', label: 'Drivers', icon: IconUsers, group: 'Fleet',
    purpose: 'Who is operating them?' },
  { key: 'maintenance', label: 'Maintenance', icon: IconWrench, group: 'Fleet',
    purpose: 'What needs fixing or preventing?' },
  { key: 'trips', label: 'Trips & History', icon: IconHistory, group: 'Fleet',
    purpose: 'What actually happened?' },
  { key: 'geofences', label: 'Geofences & Places', icon: IconZone, group: 'Fleet',
    purpose: 'Where do we operate?' },

  { key: 'fuel', label: 'Fuel & Energy', icon: IconFuel, group: 'Control',
    purpose: 'What are we consuming?' },
  { key: 'compliance', label: 'Compliance', icon: IconDoc, group: 'Control',
    purpose: 'What are we at risk of?' },
  { key: 'incidents', label: 'Incidents', icon: IconIncident, group: 'Control',
    purpose: 'What went wrong?' },
  { key: 'costs', label: 'Costs & TCO', icon: IconCoin, group: 'Control',
    purpose: 'What is it costing us?' },

  { key: 'analytics', label: 'Analytics', icon: IconChart, group: 'Insight',
    purpose: 'How are we performing?' },
  { key: 'safety', label: 'Safety & Rewards', icon: IconShield, group: 'Insight',
    purpose: 'How safely are we driving?' },
  { key: 'sustainability', label: 'Sustainability', icon: IconLeaf, group: 'Insight',
    purpose: 'What is our footprint?' },
  { key: 'ai', label: 'Fleet Intelligence', icon: IconSpark, group: 'Insight',
    purpose: 'What should we do next?' },

  { key: 'settings', label: 'Settings', icon: IconSettings, group: 'Admin',
    purpose: 'How is FleetBeat configured?' },
];

export const NAV_GROUPS = ['Operate', 'Fleet', 'Control', 'Insight', 'Admin'];
