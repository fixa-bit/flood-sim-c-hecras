import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Cartesian2,
  Cartesian3,
  CesiumTerrainProvider,
  Color,
  ConstantProperty,
  Credit,
  CustomDataSource,
  CustomHeightmapTerrainProvider,
  DiscardMissingTileImagePolicy,
  EllipsoidTerrainProvider,
  GeographicTilingScheme,
  GeoJsonDataSource,
  HeightReference,
  HeightmapTerrainData,
  HeadingPitchRange,
  ImageryLayer,
  Ion,
  LabelGraphics,
  JulianDate,
  LabelStyle,
  Math as CesiumMath,
  Matrix4,
  Rectangle,
  SingleTileImageryProvider,
  SplitDirection,
  TileMapServiceImageryProvider,
  UrlTemplateImageryProvider,
  Viewer,
  buildModuleUrl,
  createWorldTerrainAsync,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { STATIONS } from "../data/stations";
import { boundsFor } from "../data/scenarios";
import type { Scenario } from "../data/scenarios";
import type {
  DomainResult,
  Overlay,
  PopulationColumns,
  Tributary,
} from "../lib/api";
import { columnCount } from "../lib/exposure";

type RiverContext = {
  available: boolean;
  focus?: { lon: number; lat: number; height_m: number; source: string };
  rivers?: object;
};

type Props = {
  scenario: Scenario;
  domain?: DomainResult;
  overlay?: Overlay;
  compare?: Overlay;
  observed?: Overlay;
  time?: string;
  /** Population density context overlay (never model input). */
  population?: Overlay;
  /** Depth (m) at each facility for the current frame, keyed by facility id. */
  facilityDepths?: Record<string, number>;
  /** Depth at which a facility counts as flooded. */
  facilityFloodM?: number;
  tributaries?: Tributary[];
  /** 3D population columns for the shown result. */
  columnsUrl?: string;
  frameIndex?: number;
  onStation: (id: string) => void;
};

type FacilityFeature = {
  id: string;
  geometry: { coordinates: [number, number] };
  properties: { kind: string; amenity: string; name: string | null };
};
// Matches server/exposure.py DENSITY_EDGES and DENSITY_COLORS.
const POPULATION_KEY: [string, string][] = [
  ["<250", "#ffeda0"],
  ["250–1k", "#fec44f"],
  ["1k–5k", "#fd8d3c"],
  ["5k–20k", "#e34a33"],
  [">20k", "#9e0142"],
];
// Column height per resident: 500 residents = 100 m. Linear, so the flooded
// share of a column is its share of the height.
const METRES_PER_PERSON = 0.2;
// Gap between neighbouring columns, as a share of the cell size.
const COLUMN_INSET = 0.08;
const COLUMN_COLORS = {
  deep: "#b5172f",
  shallow: "#ff7a59",
  dry: "#e9d8a6",
};
type ColumnSegments = { deep: number; shallow: number; dry: number };
/**
 * Fetch, retrying network errors and server errors with increasing waits.
 * A restart of the local API must not leave terrain tiles permanently failed:
 * Cesium never re-requests a tile whose first request was rejected.
 */
async function fetchWithRetry(url: string) {
  const waits = [500, 1000, 2000, 4000, 8000];
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500 || attempt >= waits.length)
        return response;
    } catch (error) {
      if (attempt >= waits.length) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, waits[attempt]));
  }
}
const FACILITY_COLORS: Record<string, string> = {
  health: "#f4f1de",
  education: "#c9b6ff",
  emergency: "#ffd166",
};

export default function Globe({
  scenario,
  domain,
  overlay,
  compare,
  observed,
  time,
  population,
  facilityDepths,
  facilityFloodM = 0.3,
  tributaries,
  columnsUrl,
  frameIndex = 0,
  onStation,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const select = useRef(onStation);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [terrain, setTerrain] = useState("Ellipsoid · no terrain heights");
  const [split, setSplit] = useState(50);
  const [flat, setFlat] = useState(false);
  const [aerial, setAerial] = useState(true);
  const [basemapFallback, setBasemapFallback] = useState(false);
  const {
    lat: outletLat,
    lon: outletLon,
    station_id: outletStation,
  } = scenario.outlet;
  const radiusKm = scenario.domain.radius_km;
  const riverKey = `${outletLon},${outletLat}`;
  const [riverFor, setRiverFor] = useState<{
    key: string;
    value: RiverContext;
  }>();
  // Context fetched for an earlier outlet is never shown for the current one.
  const riverContext = riverFor?.key === riverKey ? riverFor.value : undefined;
  const [riverView, setRiverView] = useState(true);
  const [showRivers, setShowRivers] = useState(false);
  const [showBasin, setShowBasin] = useState(false);
  const [showPopulation, setShowPopulation] = useState(false);
  const [showFacilities, setShowFacilities] = useState(false);
  const [showTributaries, setShowTributaries] = useState(true);
  const [facilities, setFacilities] = useState<FacilityFeature[]>();
  const [facilitySource, setFacilitySource] = useState<CustomDataSource>();
  const [showColumns, setShowColumns] = useState(false);
  const [columnsFor, setColumnsFor] = useState<{
    url: string;
    value: PopulationColumns;
  }>();
  const columnData =
    columnsFor?.url === columnsUrl && columnsFor?.value.available
      ? columnsFor.value
      : undefined;
  const [columnSource, setColumnSource] = useState<CustomDataSource>();
  const [pickedColumn, setPickedColumn] = useState<number>();
  const drawnColumns = useRef(new Map<number, ColumnSegments>());
  const [cameraRevision, setCameraRevision] = useState(0);
  const aerialLayer = useRef<ImageryLayer | null>(null);
  const streetLayer = useRef<ImageryLayer | null>(null);
  const aerialChoice = useRef(aerial);
  // Requests to the online basemaps only. Terrain, model frames and other
  // local layers never count: slow local tiles must not hide good imagery.
  const imagery = useRef({ pending: 0, progressAt: 0 });
  // A fallback retries online imagery by itself, backing off on repeats.
  const fallbackRetryMs = useRef(30000);
  useLayoutEffect(() => {
    aerialChoice.current = aerial;
    select.current = onStation;
  });

  useEffect(() => {
    if (!container.current) return;
    let v: Viewer;
    let stopped = false;
    let loadingFrames: ReturnType<typeof setInterval> | undefined;
    try {
      // Bundled imagery keeps the globe available without an ion token or network.
      v = new Viewer(container.current, {
        baseLayer: false,
        terrainProvider: new EllipsoidTerrainProvider(),
        animation: false,
        timeline: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        selectionIndicator: true,
        infoBox: false,
        requestRenderMode: true,
        shouldAnimate: false,
      });
      viewer.current = v;
      // Native fetch-based terrain is outside Cesium's request scheduler. Keep
      // the loading queue advancing, then return to idle rendering when ready.
      loadingFrames = setInterval(() => {
        if (!stopped && !v.isDestroyed() && !v.scene.globe.tilesLoaded)
          v.scene.requestRender();
      }, 100);
      v.scene.globe.maximumScreenSpaceError = 4;
      v.scene.backgroundColor = Color.fromCssColorString("#0a141a");
      v.scene.globe.baseColor = Color.fromCssColorString("#17313a");
      v.scene.globe.enableLighting = false;
      v.scene.fog.enabled = false;
      v.scene.skyAtmosphere!.show = false;
      if (v.scene.skyBox) v.scene.skyBox.show = false;
      v.scene.postRender.addEventListener(() => {
        if (!stopped && container.current)
          container.current.dataset.tilesReady = String(
            v.scene.globe.tilesLoaded,
          );
      });
      TileMapServiceImageryProvider.fromUrl(
        buildModuleUrl("Assets/Textures/NaturalEarthII"),
        { tilingScheme: new GeographicTilingScheme(), maximumLevel: 5 },
      )
        .then((provider) => {
          if (!stopped) v.imageryLayers.addImageryProvider(provider, 0);
        })
        .catch(() => {
          if (!stopped)
            setError(
              "Bundled basemap unavailable; station coordinates remain available.",
            );
        });
      const detail = new UrlTemplateImageryProvider({
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        credit: new Credit(
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL)',
          true,
        ),
        maximumLevel: 19,
      });
      streetLayer.current = v.imageryLayers.addImageryProvider(detail);
      streetLayer.current.show = !aerialChoice.current;
      const photo = new UrlTemplateImageryProvider({
        url: "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        maximumLevel: 19,
        // ArcGIS can return a successful image response containing its missing
        // data notice. Discard those images so Cesium retains available parent
        // imagery instead of painting the notice over the terrain.
        tileDiscardPolicy: new DiscardMissingTileImagePolicy({
          missingImageUrl:
            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/19/0/0",
          pixelsToCheck: [
            new Cartesian2(0, 0),
            new Cartesian2(200, 20),
            new Cartesian2(20, 200),
            new Cartesian2(80, 110),
            new Cartesian2(160, 130),
          ],
          disableCheckIfAllPixelsAreTransparent: true,
        }),
        credit: new Credit(
          "Imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
          true,
        ),
      });
      for (const provider of [detail, photo]) {
        const request = provider.requestImage.bind(provider);
        provider.requestImage = (x, y, level, req) => {
          const pending = request(x, y, level, req);
          if (!pending) return pending; // throttled; Cesium asks again later
          const state = imagery.current;
          if (state.pending++ === 0) state.progressAt = performance.now();
          const done = () => {
            state.pending--;
            state.progressAt = performance.now();
          };
          Promise.resolve(pending).then(done, done);
          return pending;
        };
      }
      const photoLayer = v.imageryLayers.addImageryProvider(photo);
      photoLayer.show = aerialChoice.current;
      aerialLayer.current = photoLayer;
      photo.errorEvent.addEventListener(() => {
        if (!stopped) {
          photoLayer.show = false;
          setAerial(false);
        }
      });
      let reported = false;
      detail.errorEvent.addEventListener(() => {
        if (!reported && !stopped) {
          reported = true;
          setError(
            "Detailed basemap unavailable. Showing bundled geographic context.",
          );
        }
      });
      const token = import.meta.env.VITE_CESIUM_ION_TOKEN;
      const local = import.meta.env.VITE_LOCAL_TERRAIN_URL;
      if (token) Ion.defaultAccessToken = token;
      const promise = local
        ? CesiumTerrainProvider.fromUrl(local)
        : token
          ? createWorldTerrainAsync()
          : null;
      promise
        ?.then((provider) => {
          if (!stopped) {
            v.terrainProvider = provider;
            setTerrain(
              local
                ? "Local terrain · verify FABDEM hash"
                : "World Terrain · context only",
            );
            v.scene.requestRender();
          }
        })
        .catch(() => {
          if (!stopped)
            setError("Terrain could not load. Using the ellipsoid.");
        });
      if (!promise) {
        void fetchWithRetry("/api/terrain/metadata")
          .then((response) => response.json())
          .then((meta) => {
            if (stopped || !meta.available) return;
            const size = meta.tile_size as number;
            const heights = async (x: number, y: number, level: number) => {
              if (level <= 6) {
                const encoded = meta.coarse_heights[`${level}/${x}/${y}`] as
                  string | undefined;
                if (!encoded) return new Float32Array(size * size);
                const bytes = Uint8Array.from(atob(encoded), (char) =>
                  char.charCodeAt(0),
                );
                return new Float32Array(bytes.buffer);
              }
              const response = await fetchWithRetry(
                `/api/terrain/${level}/${x}/${y}.bin`,
              );
              if (!response.ok)
                throw new Error("Local terrain tile unavailable");
              const data = new Float32Array(await response.arrayBuffer());
              if (data.length !== size * size)
                throw new Error("Invalid local terrain tile");
              if (!stopped && !v.isDestroyed()) v.scene.requestRender();
              return data;
            };
            const provider = new CustomHeightmapTerrainProvider({
              width: size,
              height: size,
              callback: heights,
              credit: new Credit(
                'FABDEM v1.2 · <a href="https://research-information.bris.ac.uk/en/datasets/fabdem-v1-2/">CC BY-NC-SA 4.0</a>',
                true,
              ),
            });
            provider.getTileDataAvailable = (_x, _y, level) =>
              level <= meta.maximum_level;
            provider.requestTileGeometry = (x, y, level) =>
              heights(x, y, level).then(
                (buffer) =>
                  new HeightmapTerrainData({
                    buffer,
                    width: size,
                    height: size,
                    childTileMask: level >= meta.maximum_level ? 0 : 15,
                  }),
              );
            v.terrainProvider = provider;
            v.scene.globe.depthTestAgainstTerrain = true;
            setTerrain("FABDEM ~30 m · local terrain");
            v.scene.requestRender();
          })
          .catch(() => {
            if (!stopped) setTerrain("Ellipsoid · local terrain unavailable");
          });
      }
      for (const station of STATIONS) {
        v.entities.add({
          id: station.id,
          position: Cartesian3.fromDegrees(station.lon, station.lat),
          point: {
            pixelSize: station.id === "nowshera" ? 12 : 7,
            color: Color.fromCssColorString(
              station.id === "nowshera" ? "#78e7c7" : "#9faeb9",
            ),
            outlineColor: Color.fromCssColorString("#10252d"),
            outlineWidth: 2,
            heightReference: HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: station.name,
            font: "12px sans-serif",
            fillColor: Color.WHITE,
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Color.fromCssColorString("#10252d"),
            pixelOffset: new Cartesian2(0, -19),
            heightReference: HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      }
      v.selectedEntityChanged.addEventListener((entity) => {
        if (entity && STATIONS.some((s) => s.id === entity.id))
          select.current(entity.id);
      });
      // The Cesium viewer is an external system created in this effect;
      // dependent effects must re-run once it exists.
      // oxlint-disable-next-line react/set-state-in-effect
      setReady(true);
    } catch {
      setError(
        "3D rendering is unavailable on this device. Use the station catalog and scenario editor below.",
      );
    }
    return () => {
      stopped = true;
      clearInterval(loadingFrames);
      viewer.current = null;
      aerialLayer.current = null;
      streetLayer.current = null;
      if (v && !v.isDestroyed()) v.destroy();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const [lon, lat] = riverKey.split(",");
    void fetch(`/api/river-context?lon=${lon}&lat=${lat}`, {
      signal: controller.signal,
    })
      .then((response) => response.json())
      .then((value: RiverContext) => setRiverFor({ key: riverKey, value }))
      .catch(() => {});
    return () => controller.abort();
  }, [riverKey]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !ready || !riverContext?.rivers || !showRivers) return;
    let stopped = false;
    let source: GeoJsonDataSource | undefined;
    GeoJsonDataSource.load(riverContext.rivers, {
      stroke: Color.fromCssColorString("#66d9ef").withAlpha(0.45),
      strokeWidth: 1.5,
      clampToGround: true,
    })
      .then((data) => {
        if (stopped) return;
        source = data;
        void v.dataSources.add(data);
        v.scene.requestRender();
      })
      .catch(() => {});
    return () => {
      stopped = true;
      if (source && !v.isDestroyed()) v.dataSources.remove(source, true);
    };
  }, [ready, riverContext, showRivers]);

  useEffect(() => {
    if (aerialLayer.current)
      aerialLayer.current.show = aerial && !basemapFallback;
    if (streetLayer.current)
      streetLayer.current.show = !aerial && !basemapFallback;
    viewer.current?.scene.requestRender();
    const v = viewer.current;
    if (!ready || !v) return;
    if (basemapFallback) {
      const delay = fallbackRetryMs.current;
      fallbackRetryMs.current = Math.min(delay * 2, 300000);
      const retry = setTimeout(() => {
        setBasemapFallback(false);
        setError((e) => (e.startsWith("Online imagery is slow") ? "" : e));
      }, delay);
      return () => clearTimeout(retry);
    }
    // A retry starts a fresh 12 s allowance.
    imagery.current.progressAt = performance.now();
    // Fall back only when online imagery requests are outstanding and none has
    // completed for 12 s. Busy-but-progressing imagery, slow local terrain and
    // model-frame layers (which keep the globe "loading" during playback) are
    // not a stall.
    const timer = setInterval(() => {
      if (v.isDestroyed()) return;
      const { pending, progressAt } = imagery.current;
      if (pending > 0 && performance.now() - progressAt >= 12000) {
        setBasemapFallback(true);
        setError(
          "Online imagery is slow. Showing bundled context with local terrain and computed water; retrying automatically, or select Satellite to retry now.",
        );
        v.scene.requestRender();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [aerial, basemapFallback, ready]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v) return;
    v.camera.cancelFlight();
    const [west, south, east, north] = boundsFor({
      outlet: { lat: outletLat, lon: outletLon },
      domain: { radius_km: radiusKm },
    });
    v.entities.removeById("analysis-domain");
    v.entities.removeById("custom-outlet");
    v.entities.removeById("snapped-outlet");
    v.entities.add({
      id: "analysis-domain",
      rectangle: {
        coordinates: Rectangle.fromDegrees(west, south, east, north),
        fill: false,
        outline: true,
        outlineColor: Color.fromCssColorString("#88e2c3"),
        outlineWidth: 2,
      },
    });
    if (!outletStation)
      v.entities.add({
        id: "custom-outlet",
        position: Cartesian3.fromDegrees(outletLon, outletLat),
        point: { pixelSize: 12, color: Color.ORANGE },
      });
    if (domain?.snapped_outlet)
      v.entities.add({
        id: "snapped-outlet",
        position: Cartesian3.fromDegrees(
          domain.snapped_outlet.lon,
          domain.snapped_outlet.lat,
        ),
        point: { pixelSize: 9, color: Color.CYAN },
      });
    if (riverView && riverContext?.focus && !flat) {
      const point = riverContext.focus;
      v.camera.lookAt(
        Cartesian3.fromDegrees(point.lon, point.lat, point.height_m),
        new HeadingPitchRange(
          CesiumMath.toRadians(35),
          CesiumMath.toRadians(-38),
          11500,
        ),
      );
      v.camera.lookAtTransform(Matrix4.IDENTITY);
      v.scene.requestRender();
    } else
      v.camera.flyTo({
        destination: Cartesian3.fromDegrees(
          outletLon,
          outletLat - 0.1,
          radiusKm * 8000,
        ),
        orientation: { heading: 0, pitch: CesiumMath.toRadians(-75), roll: 0 },
        duration: 0.8,
      });
  }, [
    ready,
    outletLat,
    outletLon,
    outletStation,
    radiusKm,
    domain,
    riverContext,
    riverView,
    cameraRevision,
    flat,
  ]);

  useEffect(() => {
    const v = viewer.current;
    // The full upstream basin is much larger than the hydraulic reach. Loading
    // its ground-clamped geometry during every prepare/run handoff can queue
    // terrain work across the whole basin. Draw it only when requested.
    if (!ready || !v || !domain?.catchment || !showBasin) return;
    let stopped = false;
    let source: GeoJsonDataSource | undefined;
    GeoJsonDataSource.load(domain.catchment, {
      stroke: Color.ORANGE,
      fill: Color.TRANSPARENT,
      strokeWidth: 2,
      clampToGround: true,
    })
      .then((data) => {
        if (!stopped) {
          source = data;
          void v.dataSources.add(data);
          v.scene.requestRender();
        }
      })
      .catch(() => setError("Catchment overlay could not load."));
    return () => {
      stopped = true;
      if (source && !v.isDestroyed()) v.dataSources.remove(source, true);
    };
  }, [ready, domain, showBasin]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v) return;
    let stopped = false;
    const layers: ImageryLayer[] = [];
    const add = async (item: Overlay | undefined, side: SplitDirection) => {
      if (!item) return;
      try {
        const provider = await SingleTileImageryProvider.fromUrl(item.url, {
          rectangle: Rectangle.fromDegrees(...item.bounds),
        });
        if (stopped) return;
        const layer = v.imageryLayers.addImageryProvider(provider);
        layer.splitDirection = side;
        layers.push(layer);
        v.scene.requestRender();
      } catch {
        if (!stopped)
          setError(
            "A model raster could not load. Verify the published outputs.",
          );
      }
    };
    void add(overlay, compare ? SplitDirection.LEFT : SplitDirection.NONE);
    void add(compare, SplitDirection.RIGHT);
    void add(observed, SplitDirection.NONE);
    return () => {
      stopped = true;
      if (!v.isDestroyed())
        for (const layer of layers) v.imageryLayers.remove(layer, true);
    };
  }, [ready, overlay, compare, observed]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v || !population || !showPopulation) return;
    let stopped = false;
    let layer: ImageryLayer | undefined;
    void SingleTileImageryProvider.fromUrl(population.url, {
      rectangle: Rectangle.fromDegrees(...population.bounds),
    })
      .then((provider) => {
        if (stopped) return;
        // Directly above the basemaps, so model water is drawn on top of it.
        const above = Math.max(
          v.imageryLayers.indexOf(aerialLayer.current!),
          v.imageryLayers.indexOf(streetLayer.current!),
        );
        layer = v.imageryLayers.addImageryProvider(provider, above + 1);
        layer.alpha = 0.55;
        v.scene.requestRender();
      })
      .catch(() => {
        if (!stopped) setError("Population layer could not load.");
      });
    return () => {
      stopped = true;
      if (layer && !v.isDestroyed()) v.imageryLayers.remove(layer, true);
    };
  }, [ready, population, showPopulation]);

  useEffect(() => {
    if (!showFacilities || facilities) return;
    const controller = new AbortController();
    void fetch("/api/exposure/facilities", { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : { features: [] }))
      .then((data: { features: FacilityFeature[] }) =>
        setFacilities(data.features),
      )
      .catch(() => {});
    return () => controller.abort();
  }, [showFacilities, facilities]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v || !facilities?.length || !showFacilities) return;
    const source = new CustomDataSource("facilities");
    for (const facility of facilities) {
      const [lon, lat] = facility.geometry.coordinates;
      source.entities.add({
        id: facility.id,
        name: facility.properties.name ?? facility.properties.amenity,
        position: Cartesian3.fromDegrees(lon, lat),
        point: {
          pixelSize: 7,
          color: Color.fromCssColorString(
            FACILITY_COLORS[facility.properties.kind] ?? "#ffffff",
          ),
          outlineColor: Color.fromCssColorString("#10252d"),
          outlineWidth: 1.5,
          heightReference: HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
    void v.dataSources.add(source);
    // The Cesium data source is an external object created in this effect;
    // the depth-colouring effect must re-run once it exists.
    // oxlint-disable-next-line react/set-state-in-effect
    setFacilitySource(source);
    v.scene.requestRender();
    return () => {
      setFacilitySource(undefined);
      if (!v.isDestroyed()) v.dataSources.remove(source, true);
    };
  }, [ready, facilities, showFacilities]);

  useEffect(() => {
    const v = viewer.current;
    if (!facilitySource || !v || !facilities) return;
    // Flooded facilities turn red, grow and get a label; the rest keep their kind colour.
    for (const facility of facilities) {
      const entity = facilitySource.entities.getById(facility.id);
      if (!entity?.point) continue;
      const depth = facilityDepths?.[facility.id] ?? 0;
      const flooded = depth >= facilityFloodM;
      entity.point.color = new ConstantProperty(
        Color.fromCssColorString(
          flooded
            ? "#ff4d4d"
            : (FACILITY_COLORS[facility.properties.kind] ?? "#ffffff"),
        ),
      );
      entity.point.pixelSize = new ConstantProperty(flooded ? 11 : 7);
      entity.label = flooded
        ? new LabelGraphics({
            text: `${facility.properties.name ?? facility.properties.amenity} · ${depth.toFixed(1)} m`,
            font: "11px sans-serif",
            fillColor: Color.WHITE,
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Color.fromCssColorString("#3a0d0d"),
            pixelOffset: new Cartesian2(0, -16),
            heightReference: HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          })
        : undefined;
    }
    v.scene.requestRender();
  }, [facilitySource, facilities, facilityDepths, facilityFloodM]);

  useEffect(() => {
    if (!showColumns || !columnsUrl || columnsFor?.url === columnsUrl) return;
    const controller = new AbortController();
    void fetch(columnsUrl, { signal: controller.signal })
      .then((response) =>
        response.ok
          ? (response.json() as Promise<PopulationColumns>)
          : { available: false as const, reason: response.statusText },
      )
      .then((value) => setColumnsFor({ url: columnsUrl, value }))
      .catch(() => {});
    return () => controller.abort();
  }, [showColumns, columnsUrl, columnsFor]);

  // FABDEM ground heights match only the local FABDEM terrain; on any other
  // terrain the columns stand on whatever ground Cesium draws.
  const localGround = terrain.startsWith("FABDEM");
  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v || !columnData || !showColumns) return;
    const source = new CustomDataSource("population-columns");
    const reference = localGround
      ? HeightReference.NONE
      : HeightReference.RELATIVE_TO_GROUND;
    const drawn = drawnColumns.current;
    drawn.clear();
    columnData.columns.forEach((column, index) => {
      const [west, south, east, north] = column.bounds;
      const inset = COLUMN_INSET * (east - west);
      const rectangle = Rectangle.fromDegrees(
        west + inset,
        south + inset,
        east - inset,
        north - inset,
      );
      const ground = localGround ? (column.ground_m ?? 0) : 0;
      const top = ground + column.people * METRES_PER_PERSON;
      const segments = column.flooded
        ? (["deep", "shallow", "dry"] as const)
        : (["dry"] as const);
      for (const segment of segments)
        source.entities.add({
          id: `population-column:${index}:${segment}`,
          name: `${column.people.toLocaleString("en-US")} residents`,
          rectangle: {
            coordinates: rectangle,
            height: ground,
            extrudedHeight: segment === "dry" ? top : ground,
            heightReference: reference,
            extrudedHeightReference: reference,
            show: segment === "dry",
            material: Color.fromCssColorString(
              COLUMN_COLORS[segment],
            ).withAlpha(segment === "dry" ? 0.5 : 0.92),
          },
        });
      drawn.set(index, { deep: 0, shallow: 0, dry: column.people });
    });
    void v.dataSources.add(source);
    const picked = v.selectedEntityChanged.addEventListener((entity) => {
      const match = /^population-column:(\d+):/.exec(entity?.id ?? "");
      setPickedColumn(match ? Number(match[1]) : undefined);
    });
    // The Cesium data source is an external object created in this effect;
    // the per-frame effect must re-run once it exists.
    // oxlint-disable-next-line react/set-state-in-effect
    setColumnSource(source);
    v.scene.requestRender();
    return () => {
      picked();
      setColumnSource(undefined);
      setPickedColumn(undefined);
      if (!v.isDestroyed()) v.dataSources.remove(source, true);
    };
  }, [ready, columnData, showColumns, localGround]);

  useEffect(() => {
    const v = viewer.current;
    if (!columnSource || !v || !columnData) return;
    // Each flooded column fills from the ground: residents in >=1 m water,
    // then 0.3-1 m, then the rest. Only columns that changed are rebuilt.
    const drawn = drawnColumns.current;
    columnData.columns.forEach((column, index) => {
      if (!column.flooded) return;
      const shallowOrDeeper = columnCount(column.flooded[0], frameIndex);
      const deep = columnCount(column.flooded[1], frameIndex);
      const next = {
        deep,
        shallow: shallowOrDeeper - deep,
        dry: Math.max(0, column.people - shallowOrDeeper),
      };
      const last = drawn.get(index);
      if (
        last &&
        last.deep === next.deep &&
        last.shallow === next.shallow &&
        last.dry === next.dry
      )
        return;
      drawn.set(index, next);
      let base = localGround ? (column.ground_m ?? 0) : 0;
      for (const segment of ["deep", "shallow", "dry"] as const) {
        const rectangle = columnSource.entities.getById(
          `population-column:${index}:${segment}`,
        )?.rectangle;
        if (!rectangle) continue;
        const top = base + next[segment] * METRES_PER_PERSON;
        rectangle.show = new ConstantProperty(next[segment] > 0);
        rectangle.height = new ConstantProperty(base);
        rectangle.extrudedHeight = new ConstantProperty(top);
        base = top;
      }
    });
    v.scene.requestRender();
  }, [columnSource, columnData, frameIndex, localGround]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v || !tributaries?.length || !showTributaries) return;
    const source = new CustomDataSource("tributaries");
    for (const item of tributaries) {
      const coordinates = (item.geometry as { coordinates: [number, number][] })
        .coordinates;
      const color = Color.fromCssColorString(
        item.represented ? "#6ee7a8" : "#ff9f43",
      );
      source.entities.add({
        id: `tributary:${item.hyriv_id}`,
        polyline: {
          positions: Cartesian3.fromDegreesArray(coordinates.flat()),
          width: item.significance === "major" ? 4 : 2,
          material: color.withAlpha(item.significance === "major" ? 0.95 : 0.7),
          clampToGround: true,
        },
      });
      if (item.significance === "major")
        source.entities.add({
          id: `tributary-entry:${item.hyriv_id}`,
          position: Cartesian3.fromDegrees(...item.crossing),
          point: {
            pixelSize: 9,
            color,
            outlineColor: Color.fromCssColorString("#10252d"),
            outlineWidth: 2,
            heightReference: HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: `${item.name ?? "Stream"} · ${Math.round(item.upland_km2).toLocaleString("en-US")} km² · ${item.represented ? "inflow" : "no inflow"}`,
            font: "12px sans-serif",
            fillColor: color,
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Color.fromCssColorString("#10252d"),
            pixelOffset: new Cartesian2(0, -18),
            heightReference: HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
    }
    void v.dataSources.add(source);
    v.scene.requestRender();
    return () => {
      if (!v.isDestroyed()) v.dataSources.remove(source, true);
    };
  }, [ready, tributaries, showTributaries]);

  useEffect(() => {
    const v = viewer.current;
    if (v && ready && time) {
      v.clock.currentTime = JulianDate.fromIso8601(time);
      v.scene.requestRender();
    }
  }, [time, ready]);
  useEffect(() => {
    const v = viewer.current;
    if (v && ready) {
      v.scene.splitPosition = split / 100;
      v.scene.requestRender();
    }
  }, [split, ready]);

  return (
    <div className="globe-shell">
      <div ref={container} className="globe" aria-label="WGS84 station globe" />
      <div className="map-top">
        <span className="map-tag">
          <i /> WGS84 <span>/</span> PAKISTAN RIVER BASIN
        </span>
        <span className="map-tag terrain-tag">{terrain}</span>
      </div>
      <div className="map-tools">
        <button
          title="Toggle 2D / 3D"
          onClick={() => {
            if (flat) viewer.current?.scene.morphTo3D(0.5);
            else viewer.current?.scene.morphTo2D(0.5);
            setFlat(!flat);
          }}
        >
          {flat ? "3D" : "2D"}
        </button>
        <button
          title="Zoom in"
          onClick={() => viewer.current?.camera.zoomIn(15000)}
        >
          +
        </button>
        <button
          title="Zoom out"
          onClick={() => viewer.current?.camera.zoomOut(15000)}
        >
          −
        </button>
      </div>
      <div className="map-views">
        <button
          className={riverView ? "active" : ""}
          onClick={() => {
            setRiverView(true);
            setFlat(false);
            viewer.current?.scene.morphTo3D(0);
            setCameraRevision((n) => n + 1);
          }}
        >
          River view
        </button>
        <button
          className={!riverView ? "active" : ""}
          onClick={() => {
            setRiverView(false);
            setCameraRevision((n) => n + 1);
          }}
        >
          Domain overview
        </button>
        <button
          onClick={() => {
            if (basemapFallback) {
              setBasemapFallback(false);
              setAerial(true);
            } else setAerial(!aerial);
            if (error.startsWith("Online imagery is slow")) setError("");
          }}
        >
          {basemapFallback ? "Satellite" : aerial ? "Map" : "Satellite"}
        </button>
        <button
          aria-pressed={showRivers}
          className={showRivers ? "active" : ""}
          onClick={() => setShowRivers(!showRivers)}
        >
          River lines
        </button>
        {population && (
          <button
            aria-pressed={showPopulation}
            className={showPopulation ? "active" : ""}
            onClick={() => setShowPopulation(!showPopulation)}
          >
            Population
          </button>
        )}
        {columnsUrl && (
          <button
            aria-pressed={showColumns}
            className={showColumns ? "active" : ""}
            onClick={() => setShowColumns(!showColumns)}
          >
            Population 3D
          </button>
        )}
        <button
          aria-pressed={showFacilities}
          className={showFacilities ? "active" : ""}
          onClick={() => setShowFacilities(!showFacilities)}
        >
          Facilities
        </button>
        {!!tributaries?.length && (
          <button
            aria-pressed={showTributaries}
            className={showTributaries ? "active" : ""}
            onClick={() => setShowTributaries(!showTributaries)}
          >
            Tributaries
          </button>
        )}
        {domain?.catchment && (
          <button
            aria-pressed={showBasin}
            className={showBasin ? "active" : ""}
            onClick={() => setShowBasin(!showBasin)}
          >
            Basin outline
          </button>
        )}
      </div>
      {error && (
        <p className="map-error" role="status">
          {error}
        </p>
      )}
      <div className="map-caption">
        <span className="outline-key" /> Analysis boundary <span>·</span>{" "}
        {domain
          ? showBasin
            ? "Supplied basin outlined separately"
            : "Supplied basin available · outline off"
          : "Catchment not yet delineated"}
        <small>
          {riverView && riverContext?.focus
            ? "Camera centered on mapped river water · imagery date varies"
            : "Station positions are approximate until snapped and reviewed."}
        </small>
      </div>
      {((population && showPopulation) || (columnData && showColumns)) && (
        <div className="map-keys">
          {population && showPopulation && (
            <div className="population-key" aria-label="Population density key">
              People / km²
              {POPULATION_KEY.map(([label, color]) => (
                <span key={label}>
                  <i style={{ background: color }} /> {label}
                </span>
              ))}
            </div>
          )}
          {columnData && showColumns && (
            <div
              className="population-key column-key"
              aria-label="Population column key"
            >
              Residents · 100 m = {Math.round(100 / METRES_PER_PERSON)}
              <span>
                <i style={{ background: COLUMN_COLORS.deep }} /> in ≥
                {columnData.thresholds_m[1]} m water
              </span>
              <span>
                <i style={{ background: COLUMN_COLORS.shallow }} />{" "}
                {columnData.thresholds_m[0]}–{columnData.thresholds_m[1]} m
              </span>
              <span>
                <i style={{ background: COLUMN_COLORS.dry }} /> below{" "}
                {columnData.thresholds_m[0]} m or dry
              </span>
            </div>
          )}
          {pickedColumn !== undefined &&
            columnData?.columns[pickedColumn] &&
            showColumns && (
              <ColumnReadout
                people={columnData.columns[pickedColumn].people}
                shallow={columnCount(
                  columnData.columns[pickedColumn].flooded?.[0],
                  frameIndex,
                )}
                deep={columnCount(
                  columnData.columns[pickedColumn].flooded?.[1],
                  frameIndex,
                )}
                thresholds={columnData.thresholds_m}
              />
            )}
        </div>
      )}
      {compare && (
        <div className="map-split">
          <label>
            A / B split
            <input
              aria-label="Comparison split"
              type="range"
              min="5"
              max="95"
              value={split}
              onChange={(e) => setSplit(+e.target.value)}
            />
          </label>
        </div>
      )}
    </div>
  );
}

function ColumnReadout({
  people,
  shallow,
  deep,
  thresholds,
}: {
  people: number;
  shallow: number;
  deep: number;
  thresholds: number[];
}) {
  const format = (n: number) => n.toLocaleString("en-US");
  return (
    <p className="column-readout" role="status">
      <strong>{format(people)} residents</strong> in this column ·{" "}
      {format(shallow)} in ≥{thresholds[0]} m water, {format(deep)} in ≥
      {thresholds[1]} m now
    </p>
  );
}
