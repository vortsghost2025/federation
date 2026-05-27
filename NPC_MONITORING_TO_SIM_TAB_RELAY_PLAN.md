# NPC Monitoring to Sim Tab Relay Plan

## Overview
This plan outlines how to relay monitored NPC responses to a real-time simulation tab in the federation frontend. The solution leverages existing Redis-based data storage and the federation's map endpoint architecture to avoid modifying core simulation files.

## Existing Infrastructure Analysis

### Data Storage
The federation game stores NPC cognition data in Redis with these key patterns:
- `npc_mood:{char_id}` - Current mood state
- `npc_decisions:{char_id}` - ZSET of recent decisions (sorted by timestamp)
- `npc_actions:{char_id}` - ZSET of recent actions
- `npc_thoughts:{char_id}` - ZSET of recent thoughts
- `npc_goals:{char_id}` - LIST of current goals
- `npc_faction_context:{char_id}` - Faction affiliation data
- `npc_profiles` - Bulk JSON of all NPC profiles
- `world_state` - HASH of current world metrics

### Available Endpoints
- `/map/data` - Aggregates all visualization data including NPC information
- Systems map already displays faction and NPC data in federationpublichtml/systems/

## Solution Design

### 1. Data Availability Strategy
The monitoring data is already available through the existing Redis storage and `/map/data` endpoint. No new backend endpoints are needed.

**Data Flow:**
```
Simulation Engine → NPC Cognition Layer → Redis Storage → /map/data Endpoint → Frontend
```

**Available Data Points for Monitoring:**
- NPC mood states and mood colors
- Latest decisions with reasoning and action descriptions
- Recent actions and action types
- Current thoughts
- Active goals and goal status
- Faction affiliations
- Rich lore/backstories
- Relationship maps between NPCs

### 2. UI Component/Tab Specification

#### Tab Location
Add a new "NPC Monitor" tab to the existing navigation in federationpublichtml/index.html alongside:
- Captain's Log
- Systems Map
- Lore Archive
- Creature Codex
- Rival Roster
- Shadow Domain
- GitHub

#### Tab Content Structure
The NPC Monitor tab will display:

**Header Section:**
- Title: "NPC Response Monitor"
- Subtitle: "Real-time observation of NPC cognition and decision-making"
- Last updated timestamp

**Main Display Sections:**

1. **Active NPCs Panel** (Grid view)
   - Cards for each NPC showing:
     - Name, title, and avatar (initial or icon)
     - Current mood with color indicator
     - Faction affiliation
     - Latest decision category
     - "View Details" button

2. **Detailed View Panel** (Accordion or modal)
   When an NPC card is clicked:
   - Full NPC profile (name, title, description)
   - Current mood and mood color visualization
   - Latest decision with:
     - Category
     - Reasoning (1-2 sentences)
     - Action description
     - Target (if any)
   - Recent thoughts (last 3)
   - Recent actions (last 3)
   - Current goals
   - Relationship map (top 3 allies/rivals)
   - Faction lore excerpt

3. **System Metrics Panel**
   - World state indicators (threat level, morale, anomaly activity, etc.)
   - Cognition statistics:
     - Leaders cognized this tick
     - Specialists cognized this tick
     - Triggers detected
     - Successful LLM calls vs failed

4. **Live Feed Panel** (Optional auto-scrolling)
   - Recent NPC decisions as they occur
   - Timestamped entries
   - Color-coded by faction or mood

### 3. Implementation Approach

#### Frontend Modifications (Non-Core)
1. **HTML Update** (`federationpublichtml/index.html`):
   - Add new nav item: `<a href="npc-monitor/">NPC Monitor</a>`
   - Create `federationpublichtml/npc-monitor/index.html`

2. **New Page Structure** (`federationpublichtml/npc-monitor/index.html`):
   - Reuse existing CSS styling from main index.html
   - Implement responsive grid for NPC cards
   - JavaScript for:
     - Fetching data from `/map/data` endpoint
     - Processing and formatting NPC data
     - UI updates and interactions
     - Optional polling for real-time updates (every 5-10 seconds)

3. **JavaScript Implementation**:
   - Fetch data from `/map/data` (already provides NPC array)
   - Transform raw data into monitor-friendly format
   - Implement card click handlers to show detailed view
   - Add auto-refresh capability with visual indicator
   - Error handling for missing data or endpoint failures

#### Backend Considerations
- **No modifications needed** to core simulation files
- Existing `/map/data` endpoint already aggregates all required data
- Redis storage is already populated by NPC cognition layer
- If additional data points are needed, they can be added to the map endpoint without changing simulation logic

### 4. Real-Time Updates Strategy

#### Polling Approach (Recommended for simplicity)
- JavaScript `setInterval` to fetch `/map/data` every 5-10 seconds
- Compare fetched data with current display
- Update only changed elements to minimize DOM manipulation
- Show "Last updated: [timestamp]" indicator
- Visual indicator during updates (subtle spinner or highlight)

#### Alternative: EventSource/WebSocket
If real-time push is required in future:
- Could add SSE endpoint streaming cognition events
- Would require minor backend addition but still no simulation changes
- For initial implementation, polling is sufficient and simpler

### 5. User Experience Considerations

#### Visual Design
- Reuse existing federation color scheme (#ff7a18 accents, #000 background)
- Mood colors from existing MOOD_COLORS map
- Card-based UI consistent with existing sections
- Responsive design for various screen sizes

#### Accessibility
- Proper ARIA labels for interactive elements
- Keyboard navigable tab interface
- Sufficient color contrast for mood indicators
- Screen reader friendly live regions for updates

#### Performance
- Minimize data transfer by only fetching needed fields
- Efficient DOM updates (only change what's necessary)
- Reasonable polling interval (5-10 seconds) to avoid excessive load
- Cache static elements (likes lore, titles) when possible

### 6. Security and Reliability

#### Error Handling
- Graceful degradation if `/map/data` endpoint unavailable
- Display friendly error messages with retry option
- Show last known good data when updates fail
- Log errors to console for debugging (visible to developers only)

#### Data Validation
- Sanitize all data before inserting into DOM
- Handle missing or null fields gracefully
- Validate data types before processing
- Provide fallback values for missing optional fields

### 7. Extension Points

#### Future Enhancements
1. **Filtering Controls**:
   - Filter by faction
   - Filter by mood
   - Filter by decision category
   - Search NPCs by name

2. **Timeline View**:
   - Show NPC decision history over time
   - Visualize cognition patterns

3. **Comparison Mode**:
   - Compare two NPCs side-by-side
   - Track relationship evolution

4. **Export Functionality**:
   - Export current monitor state as JSON
   - Generate reports of NPC behavior

#### Configuration Options
- Polling interval (configurable via JS constant)
- Number of recent thoughts/actions to display
- Enable/disable auto-scroll in live feed
- Default view (grid vs list)

## Implementation Steps

### Phase 1: Basic Implementation
1. Create `federationpublichtml/npc-monitor/` directory
2. Create basic `index.html` with tab structure
3. Implement JavaScript to fetch and display NPC data from `/map/data`
4. Add nav link to main index.html
5. Style using existing CSS patterns

### Phase 2: Enhanced Features
1. Add detailed view modals/accordions
2. Implement live feed of recent decisions
3. Add system metrics panel
4. Improve error handling and loading states

### Phase 3: Polish and Optimization
1. Add visual refinements and animations
2. Optimize polling and DOM updates
3. Add accessibility enhancements
4. Test across different screen sizes

## Verification Approach

### Manual Verification
1. Confirm new tab appears in navigation
2. Verify NPC data loads and displays correctly
3. Check that clicking NPC shows detailed information
4. Validate that data updates periodically
5. Ensure responsive behavior on different screen sizes

### Automated Verification (Future)
1. Could add simple tests to verify:
   - Endpoint returns expected NPC data structure
   - JavaScript processes data correctly
   - UI updates when data changes

## Conclusion

This plan leverages existing federation infrastructure to create an NPC monitoring tab without modifying core simulation files. By using the already-available `/map/data` endpoint and Redis storage patterns, we can provide real-time visibility into NPC cognition and decision-making while maintaining system integrity and following established frontend patterns.

The solution is incremental, starting with basic data display and enhancing over time, and respects the federation's architectural principles of using existing systems and avoiding unnecessary modifications to core components.