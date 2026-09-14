// The module router: every navigation entry resolves to a real page.

import type { ReactNode } from 'react';
import type { BaseData } from '../map/style';
import { Ai } from './Ai';
import { Alerts } from './Alerts';
import { Analytics } from './Analytics';
import { Compliance } from './Compliance';
import { Costs } from './Costs';
import { Dispatch } from './Dispatch';
import { DriverApp } from './DriverApp';
import { Drivers } from './Drivers';
import { Fuel } from './Fuel';
import { Geofences } from './Geofences';
import { Incidents } from './Incidents';
import { LiveTracking } from './LiveTracking';
import { Maintenance } from './Maintenance';
import { PlatformAdmin } from './PlatformAdmin';
import { Safety } from './Safety';
import { Settings } from './Settings';
import { Sustainability } from './Sustainability';
import { Tasks } from './Tasks';
import { Trips } from './Trips';
import { Vehicles } from './Vehicles';

export function renderModule(page: string, base: BaseData): ReactNode {
  switch (page) {
    case 'live': return <LiveTracking base={base} />;
    case 'alerts': return <Alerts />;
    case 'dispatch': return <Dispatch base={base} />;
    case 'tasks': return <Tasks base={base} />;
    case 'vehicles': return <Vehicles />;
    case 'drivers': return <Drivers />;
    case 'maintenance': return <Maintenance />;
    case 'trips': return <Trips base={base} />;
    case 'geofences': return <Geofences base={base} />;
    case 'fuel': return <Fuel />;
    case 'compliance': return <Compliance />;
    case 'incidents': return <Incidents />;
    case 'costs': return <Costs />;
    case 'analytics': return <Analytics />;
    case 'safety': return <Safety />;
    case 'sustainability': return <Sustainability />;
    case 'ai': return <Ai />;
    case 'settings': return <Settings />;
    case 'driver-app': return <DriverApp />;
    case 'platform': return <PlatformAdmin />;
    default: return <LiveTracking base={base} />;
  }
}
