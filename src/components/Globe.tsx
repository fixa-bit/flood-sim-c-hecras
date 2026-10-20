import { useEffect, useRef, useState } from "react";
import {
  Cartesian2,
  Cartesian3,
  CesiumTerrainProvider,
  Color,
  Credit,
  CustomHeightmapTerrainProvider,
  EllipsoidTerrainProvider,
  GeographicTilingScheme,
  GeoJsonDataSource,
  HeightReference,
  HeightmapTerrainData,
  HeadingPitchRange,
  ImageryLayer,
  Ion,
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
import type { DomainResult, Overlay } from "../lib/api";

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
  onStation: (id: string) => void;
};

export default function Globe({
  scenario,
  domain,
  overlay,
  compare,
  observed,
  time,
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
  const [riverContext, setRiverContext] = useState<RiverContext>();
  const [riverView, setRiverView] = useState(true);
  const [showRivers, setShowRivers] = useState(false);
  const [cameraRevision, setCameraRevision] = useState(0);
  const aerialLayer = useRef<ImageryLayer | null>(null);
  const aerialChoice = useRef(aerial);
  aerialChoice.current = aerial;
  select.current = onStation;

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
      v.imageryLayers.addImageryProvider(detail);
      const photo = new UrlTemplateImageryProvider({
        url: "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        maximumLevel: 19,
        credit: new Credit(
          "Imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
          true,
        ),
      });
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
        void fetch("/api/terrain/metadata")
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
              const response = await fetch(
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
            provider.getTileDataAvailable = (_x, _y, level) => level <= meta.maximum_level;
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
      if (v && !v.isDestroyed()) v.destroy();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setRiverContext(undefined);
    void fetch(
      `/api/river-context?lon=${scenario.outlet.lon}&lat=${scenario.outlet.lat}`,
      { signal: controller.signal },
    )
      .then((response) => response.json())
      .then(setRiverContext)
      .catch(() => {});
    return () => controller.abort();
  }, [scenario.outlet.lon, scenario.outlet.lat]);

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
    if (aerialLayer.current) aerialLayer.current.show = aerial;
    viewer.current?.scene.requestRender();
  }, [aerial]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v) return;
    const [west, south, east, north] = boundsFor(scenario);
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
    if (!scenario.outlet.station_id)
      v.entities.add({
        id: "custom-outlet",
        position: Cartesian3.fromDegrees(
          scenario.outlet.lon,
          scenario.outlet.lat,
        ),
        point: { pixelSize: 12, color: Color.ORANGE },
      });
    if (domain)
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
          scenario.outlet.lon,
          scenario.outlet.lat - 0.1,
          scenario.domain.radius_km * 8000,
        ),
        orientation: { heading: 0, pitch: CesiumMath.toRadians(-75), roll: 0 },
        duration: 0.8,
      });
  }, [
    ready,
    scenario.outlet.lat,
    scenario.outlet.lon,
    scenario.outlet.station_id,
    scenario.domain.radius_km,
    domain,
    riverContext,
    riverView,
    cameraRevision,
    flat,
  ]);

  useEffect(() => {
    const v = viewer.current;
    if (!ready || !v || !domain?.catchment) return;
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
  }, [ready, domain]);

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
        <button onClick={() => setAerial(!aerial)}>
          {aerial ? "Map" : "Satellite"}
        </button>
        <button aria-pressed={showRivers} className={showRivers ? "active" : ""} onClick={() => setShowRivers(!showRivers)}>
          River lines
        </button>
      </div>
      {error && (
        <p className="map-error" role="status">
          {error}
        </p>
      )}
      <div className="map-caption">
        <span className="outline-key" /> Analysis boundary <span>·</span>{" "}
        {domain
          ? "Supplied basin outlined separately"
          : "Catchment not yet delineated"}
        <small>
          {riverView && riverContext?.focus
            ? "Camera centered on mapped river water · imagery date varies"
            : "Station positions are approximate until snapped and reviewed."}
        </small>
      </div>
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
