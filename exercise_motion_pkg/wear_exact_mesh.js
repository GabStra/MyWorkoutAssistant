    // Direct JavaScript port of buildSingleLowPolyMesh in SkeletonMotionPreview.kt.
    const wearExactGeometry = new THREE.BufferGeometry();
    const wearExactMesh = new THREE.Mesh(
      wearExactGeometry,
      new THREE.MeshBasicMaterial({
        vertexColors: true,
        side: THREE.FrontSide,
        toneMapped: false,
      })
    );
    wearExactMesh.visible = false;
    scene.add(wearExactMesh);
    let wearStableBodyProportions = null;
    const wearStableSegmentLengths = new Map();

    const wearLimbs = [
      ["left_hip", "left_knee", .27, .215, .46, 1.24, .42],
      ["left_knee", "left_ankle", .225, .165, .44, 1.18, .46],
      ["right_hip", "right_knee", .27, .215, .46, 1.24, .42],
      ["right_knee", "right_ankle", .225, .165, .44, 1.18, .46],
      ["left_shoulder", "left_elbow", .30, .225, .44, 1.26, .48],
      ["left_elbow", "left_wrist", .235, .175, .42, 1.16, .40],
      ["right_shoulder", "right_elbow", .30, .225, .44, 1.26, .48],
      ["right_elbow", "right_wrist", .235, .175, .42, 1.16, .40],
    ];
    const wearCapNames = new Set([
      "left_hip", "right_hip", "left_shoulder", "right_shoulder",
      "left_elbow", "right_elbow", "left_wrist", "right_wrist",
      "left_knee", "right_knee",
      "left_ankle", "right_ankle",
    ]);
    let wearCurrentSides = new Map();
    let wearLastDirections = new Map();
    let wearStableSidesByFrame = null;
    let wearStableFrames = null;
    let wearStableBodyAxesByFrame = null;

    function wearUnit(vector, fallback) {
      return vector.lengthSq() > 1e-8 ? vector.normalize() : fallback.clone();
    }

    function wearAxes(joints) {
      const hipSide = joints.left_hip && joints.right_hip
        ? joints.right_hip.clone().sub(joints.left_hip)
        : null;
      const shoulderSide = joints.left_shoulder && joints.right_shoulder
        ? joints.right_shoulder.clone().sub(joints.left_shoulder)
        : null;
      const side = wearUnit(
        hipSide ?? shoulderSide ?? new THREE.Vector3(1, 0, 0),
        new THREE.Vector3(1, 0, 0)
      );
      const up = joints.pelvis && joints.neck
        ? wearUnit(joints.neck.clone().sub(joints.pelvis), new THREE.Vector3(0, 1, 0))
        : new THREE.Vector3(0, 1, 0);
      return {
        side,
        up,
        forward: wearUnit(side.clone().cross(up), new THREE.Vector3(0, 0, 1)),
      };
    }

    function wearStableSide(direction, axes) {
      const side = axes.side.clone().addScaledVector(direction, -axes.side.dot(direction));
      if (side.length() > .18) return side.normalize();
      const forward = axes.forward.clone().addScaledVector(direction, -axes.forward.dot(direction));
      if (forward.length() > .18) return forward.normalize();
      return wearUnit(
        axes.up.clone().addScaledVector(direction, -axes.up.dot(direction)),
        axes.forward
      );
    }

    function wearSpineRingAxes(previous, center, next, bodyAxes) {
      const tangent = wearUnit(
        next.clone().sub(previous),
        wearUnit(next.clone().sub(center), bodyAxes.up)
      );
      const side = wearUnit(
        bodyAxes.side.clone().addScaledVector(tangent, -bodyAxes.side.dot(tangent)),
        bodyAxes.side
      );
      return {
        side,
        up: tangent,
        forward: wearUnit(side.clone().cross(tangent), bodyAxes.forward),
      };
    }

    function wearSpineProgress(hipCenter, neck, point) {
      const axis = neck.clone().sub(hipCenter);
      const lengthSq = axis.lengthSq();
      if (lengthSq <= 1e-6) return 0.5;
      return Math.max(0, Math.min(1, point.clone().sub(hipCenter).dot(axis) / lengthSq));
    }

    function wearTorsoBodyWidth(hipWidth, shoulderWidth, progress) {
      const t = Math.max(0, Math.min(1, progress));
      return hipWidth + (shoulderWidth - hipWidth) * t;
    }

    function wearAlignRingAxes(reference, candidate) {
      const up = candidate.up;
      let side = candidate.side;
      if (side.dot(reference.side) < 0) {
        side = side.clone().multiplyScalar(-1);
      }
      return {
        side,
        up,
        forward: wearUnit(side.clone().cross(up), candidate.forward),
      };
    }

    function wearCoordinateLegSides(joints, sides, referenceSides = null) {
      for (const leg of ["left", "right"]) {
        const hip = joints[`${leg}_hip`];
        const knee = joints[`${leg}_knee`];
        const ankle = joints[`${leg}_ankle`];
        const toe = joints[`${leg}_foot`];
        if (!hip || !knee || !ankle || !toe) continue;
        const thigh = knee.clone().sub(hip);
        const shin = ankle.clone().sub(knee);
        const foot = toe.clone().sub(ankle);
        if (Math.min(thigh.lengthSq(), shin.lengthSq(), foot.lengthSq()) < 1e-8) continue;
        thigh.normalize(); shin.normalize(); foot.normalize();
        const thighKey = `${leg}_hip->${leg}_knee`;
        const shinKey = `${leg}_knee->${leg}_ankle`;
        const footKey = `${leg}_ankle->${leg}_foot`;
        const ankleSide = foot.clone().cross(shin.clone().negate());
        const kneeSide = thigh.clone().cross(shin);
        // One transverse axis belongs to the leg's knee hinge. The ankle
        // plane supplies its direction and the straight-knee fallback.
        const ankleReference = ankleSide.lengthSq() > 1e-8
          ? ankleSide.normalize()
          : null;
        const previous = referenceSides?.get(shinKey);
        const transported = previous?.clone().addScaledVector(shin, -previous.dot(shin));
        const reference = transported && transported.lengthSq() > 1e-8
          ? transported.normalize() : ankleReference;
        // sin(20 degrees): below this bend, positional noise is amplified
        // into apparent axial rotation. Transport the established frame.
        const bend = kneeSide.length();
        let side = bend > .342 ? kneeSide.multiplyScalar(1 / bend) : reference?.clone();
        if (!side) continue;
        if (reference && side.dot(reference) < 0) side.negate();
        // A nearly straight knee has no reliable bend plane. Keep its
        // transported frame, and acquire an observed plane gradually.
        if (reference && previous) {
          const confidence = Math.max(0, Math.min(1, (bend - .342) / .3));
          side = reference.clone().lerp(side, .2 * confidence).normalize();
        }
        sides.set(thighKey, side.clone());
        sides.set(shinKey, side.clone());
        sides.set(footKey, wearUnit(
          side.clone().addScaledVector(foot, -side.dot(foot)),
          reference ?? side
        ));
      }
      return sides;
    }

    function wearLimbSides(joints, axes, preferredSides = null) {
      const current = new Map();
      const directions = new Map();
      for (const [startName, endName] of wearLimbs) {
        if (!joints[startName] || !joints[endName]) continue;
        const direction = joints[endName].clone().sub(joints[startName]);
        if (direction.lengthSq() <= 1e-8) continue;
        direction.normalize();
        const key = `${startName}->${endName}`;
        directions.set(key, direction.clone());
        const preferred = preferredSides?.get(key);
        const projected = preferred
          ? preferred.clone().addScaledVector(direction, -preferred.dot(direction))
          : null;
        current.set(
          key,
          projected && projected.lengthSq() > 1e-8
            ? projected.normalize()
            : wearStableSide(direction, axes)
        );
      }
      if (preferredSides?.has("left_knee->left_ankle") || preferredSides?.has("right_knee->right_ankle")) {
        for (const leg of ["left", "right"]) {
          const key = `${leg}_ankle->${leg}_foot`;
          if (preferredSides.has(key)) current.set(key, preferredSides.get(key));
        }
      } else {
        wearCoordinateLegSides(joints, current, preferredSides);
      }
      wearCurrentSides = current;
      wearLastDirections = directions;
      return current;
    }

    function wearBuildStableSidesByFrame() {
      let previousSides = new Map();
      const directionsByFrame = [];
      const previousRenderFrame = activeRenderFrame;
      const result = (playbackState.frames ?? []).map((frame) => {
        activeRenderFrame = frame;
        const joints = {};
        const frameTranslation = getFrameTranslation(frame);
        for (const [name, point] of Object.entries(frame.joints)) {
          joints[name] = toWorldPoint(point, frameTranslation, fixedRoot, true, name);
        }
        const axes = wearAxes(joints);
        const currentSides = new Map();
        const directions = new Map();
        for (const [startName, endName] of wearLimbs) {
          if (!joints[startName] || !joints[endName]) continue;
          const direction = joints[endName].clone().sub(joints[startName]);
          if (direction.lengthSq() <= 1e-8) continue;
          direction.normalize();
          const key = `${startName}->${endName}`;
          const previous = previousSides.get(key);
          directions.set(key, direction.clone());
          const transported = previous
            ? previous.clone().addScaledVector(direction, -previous.dot(direction))
            : null;
          let side = transported && transported.lengthSq() > 1e-8
            ? transported.normalize()
            : wearStableSide(direction, axes);
          if (previous && side.dot(previous) < 0) side.multiplyScalar(-1);
          currentSides.set(key, side);
        }
        wearCoordinateLegSides(joints, currentSides, previousSides);
        previousSides = currentSides;
        directionsByFrame.push(directions);
        return currentSides;
      });
      if (playbackState.loopable && result.length > 1) {
        // A transported frame accumulates roll around a closed path. Spread
        // that residual over the cycle, rather than releasing it at restart.
        const last = result.length - 1;
        for (const [key, firstSide] of result[0]) {
          const firstAxis = directionsByFrame[0].get(key);
          const lastAxis = directionsByFrame[last].get(key);
          const lastSide = result[last].get(key);
          if (!firstAxis || !lastAxis || !lastSide) continue;
          const transported = lastSide.clone().applyQuaternion(
            new THREE.Quaternion().setFromUnitVectors(lastAxis, firstAxis));
          const residual = Math.atan2(firstAxis.dot(
            new THREE.Vector3().crossVectors(transported, firstSide)), transported.dot(firstSide));
          result.forEach((sides, index) => {
            const side = sides.get(key), axis = directionsByFrame[index].get(key);
            if (side && axis) sides.set(key, side.clone().applyAxisAngle(axis, residual * index / result.length));
          });
        }
      }
      activeRenderFrame = previousRenderFrame;
      return result;
    }

    function wearBuildStableBodyAxesByFrame() {
      const previousRenderFrame = activeRenderFrame;
      const rawAxes = (playbackState.frames ?? []).map((frame) => {
        activeRenderFrame = frame;
        const joints = {};
        const frameTranslation = getFrameTranslation(frame);
        for (const [name, point] of Object.entries(frame.joints)) {
          joints[name] = toWorldPoint(point, frameTranslation, fixedRoot, true, name);
        }
        return wearAxes(joints);
      });
      activeRenderFrame = previousRenderFrame;
      const radius = 3;
      return rawAxes.map((centerAxes, frameIndex) => {
        const side = new THREE.Vector3();
        const up = new THREE.Vector3();
        for (
          let sampleIndex = Math.max(0, frameIndex - radius);
          sampleIndex <= Math.min(rawAxes.length - 1, frameIndex + radius);
          sampleIndex += 1
        ) {
          const weight = radius + 1 - Math.abs(sampleIndex - frameIndex);
          const sample = rawAxes[sampleIndex];
          side.addScaledVector(
            sample.side,
            sample.side.dot(centerAxes.side) < 0 ? -weight : weight
          );
          up.addScaledVector(sample.up, sample.up.dot(centerAxes.up) < 0 ? -weight : weight);
        }
        const stableUp = wearUnit(up, centerAxes.up);
        const stableSide = wearUnit(
          side.addScaledVector(stableUp, -side.dot(stableUp)),
          centerAxes.side
        );
        return {
          side: stableSide,
          up: stableUp,
          forward: wearUnit(stableSide.clone().cross(stableUp), centerAxes.forward),
        };
      });
    }

    function inspectWearExactLimbOrientations() {
      return [...wearCurrentSides.entries()].map(([key, side]) => ({
        key,
        side: side.toArray(),
        direction: wearLastDirections.get(key)?.toArray() ?? null,
      }));
    }

    function wearMeshData() {
      return { vertices: [], faces: [] };
    }

    function wearVertex(mesh, point) {
      mesh.vertices.push(point);
      return mesh.vertices.length - 1;
    }

    function wearFace(mesh, indices, fill) {
      mesh.faces.push({ indices, fill });
    }

    function wearBoxRing(mesh, center, side, depth, halfWidth, halfDepth) {
      return [
        center.clone().addScaledVector(side, halfWidth).addScaledVector(depth, halfDepth),
        center.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, halfDepth),
        center.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, -halfDepth),
        center.clone().addScaledVector(side, halfWidth).addScaledVector(depth, -halfDepth),
      ].map((point) => wearVertex(mesh, point));
    }

    function wearTorsoRing(
      mesh, center, side, depth, halfWidth, halfDepth,
      latWidthScale, latDepthScale, erectorWidthScale, erectorDepthScale,
      grooveWidthScale, grooveDepthScale, backDepthTracker = null,
      backDepthBoost = 1.0, backCenterBias = null, minBackDepth = null
    ) {
      const latScale = Math.max(1.0, Math.min(1.18, latWidthScale));
      const frontDepth = Math.max(
        halfDepth * 0.85,
        Math.min(halfDepth * 1.08, halfDepth * (0.90 + latDepthScale * 0.08))
      );
      let backDepth = Math.max(
        halfDepth * 0.86,
        Math.min(halfDepth * 1.12, halfDepth * (0.92 + erectorDepthScale * 0.04))
      ) * backDepthBoost;
      if (backDepthTracker && backDepthTracker.value > 0) {
        backDepth = Math.max(backDepth, backDepthTracker.value);
      }
      if (minBackDepth != null) {
        backDepth = Math.max(backDepth, minBackDepth);
      }
      if (backDepthTracker) {
        backDepthTracker.value = Math.max(backDepthTracker.value, backDepth);
      }
      const width = halfWidth * latScale;
      return wearDirectionalRing(
        mesh, center, side, depth, width, frontDepth, backDepth, backCenterBias
      );
    }

    function wearDirectionalRing(
      mesh, center, side, depth, halfWidth, frontDepth, backDepth, backCenterBias = null, cornerBevel = 0
    ) {
      const backCenter = backCenterBias ? center.clone().add(backCenterBias) : center;
      const corners = [
        center.clone().addScaledVector(side, halfWidth).addScaledVector(depth, frontDepth),
        center.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, frontDepth),
        backCenter.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, -backDepth),
        backCenter.clone().addScaledVector(side, halfWidth).addScaledVector(depth, -backDepth),
      ];
      const bevel = Math.max(0, Math.min(.45, cornerBevel));
      const outline = bevel > 0 ? corners.flatMap((corner, index) => [
        corner.clone().lerp(corners[(index + 3) % 4], bevel),
        corner.clone().lerp(corners[(index + 1) % 4], bevel),
      ]) : corners;
      return outline.map(point => wearVertex(mesh, point));
    }

    function wearRing(mesh, center, side, depth, halfWidth, halfDepth, sides) {
      return Array.from({ length: Math.max(4, sides) }, (_, index) => {
        const angle = 2 * Math.PI * index / sides;
        return wearVertex(
          mesh,
          center.clone()
            .addScaledVector(side, Math.cos(angle) * halfWidth)
            .addScaledVector(depth, Math.sin(angle) * halfDepth)
        );
      });
    }

    function wearStrip(mesh, lower, upper, fill) {
      if (upper.length === lower.length * 2) {
        for (let i=0; i<lower.length; i++) {
          const next=(i+1)%lower.length;
          wearFace(mesh,[lower[i],upper[i*2],upper[i*2+1]],fill);
          wearFace(mesh,[lower[i],upper[i*2+1],upper[next*2],lower[next]],fill);
        }
        return;
      }
      if (lower.length === upper.length * 2) {
        for (let i=0; i<upper.length; i++) {
          const next=(i+1)%upper.length;
          wearFace(mesh,[lower[i*2],upper[i],lower[i*2+1]],fill);
          wearFace(mesh,[lower[i*2+1],upper[i],upper[next],lower[next*2]],fill);
        }
        return;
      }
      const count = Math.min(lower.length, upper.length);
      for (let index = 0; index < count; index += 1) {
        const next = (index + 1) % count;
        wearFace(mesh, [lower[index], upper[index], upper[next], lower[next]], fill);
      }
    }

    function wearCap(mesh, ring, fill) {
      if (ring.length === 3 || ring.length === 4) {
        wearFace(mesh, ring, fill);
        return;
      }
      for (let index = 1; index < ring.length - 1; index += 1) {
        wearFace(mesh, [ring[0], ring[index], ring[index + 1]], fill);
      }
    }

    function wearFan(mesh, center, ring, fill) {
      for (let index = 0; index < ring.length; index += 1) {
        wearFace(mesh, [center, ring[index], ring[(index + 1) % ring.length]], fill);
      }
    }

    function wearSphere(mesh, center, axes, radius, fill) {
      const bottom = wearVertex(mesh, center.clone().addScaledVector(axes.up, -radius));
      const top = wearVertex(mesh, center.clone().addScaledVector(axes.up, radius));
      const lower = wearRing(
        mesh, center.clone().addScaledVector(axes.up, -radius * .50),
        axes.side, axes.forward, radius * .866, radius * .866, 8
      );
      const middle = wearRing(
        mesh, center,
        axes.side, axes.forward, radius, radius, 8
      );
      const upper = wearRing(
        mesh, center.clone().addScaledVector(axes.up, radius * .50),
        axes.side, axes.forward, radius * .866, radius * .866, 8
      );
      wearFan(mesh, bottom, lower, fill);
      wearStrip(mesh, lower, middle, fill);
      wearStrip(mesh, middle, upper, fill);
      wearFan(mesh, top, [...upper].reverse(), fill);
    }

    function wearClearance(name, width) {
      if (!wearCapNames.has(name)) return 0;
      if (name.includes("hip")) return width * .12;
      if (name.includes("shoulder")) return width * .12;
      if (name.includes("ankle")) return width * 1.10;
      return width * .08;
    }

    function wearSegment(
      mesh, start, end, axes, startWidth, endWidth, depthScale, fill,
      startInset = 0, endInset = 0, preferredSide = null,
      muscleBulgeScale = 1, muscleBulgePosition = .5
    ) {
      const segment = end.clone().sub(start);
      const length = segment.length();
      if (length <= .0001) return;
      const direction = segment.multiplyScalar(1 / length);
      const maxInset = length * .15;
      const safeStart = start.clone().addScaledVector(direction, Math.min(startInset, maxInset));
      const safeEnd = end.clone().addScaledVector(direction, -Math.min(endInset, maxInset));
      if (safeEnd.distanceToSquared(safeStart) <= 1e-8) return;
      const projected = preferredSide
        ? preferredSide.clone().addScaledVector(direction, -preferredSide.dot(direction))
        : wearStableSide(direction, axes);
      const side = wearUnit(projected, wearStableSide(direction, axes));
      const depth = wearUnit(side.clone().cross(direction), axes.forward);
      const limbRing = (center, width) =>
        wearBoxRing(mesh, center, side, depth, width * .5, width * depthScale);
      const lower = limbRing(safeStart, startWidth);
      const upper = limbRing(safeEnd, endWidth);
      if (muscleBulgeScale > 1) {
        const position = Math.max(.2, Math.min(.8, muscleBulgePosition));
        const center = safeStart.clone().lerp(safeEnd, position);
        const interpolatedWidth = startWidth + (endWidth - startWidth) * position;
        const bulgeWidth = Math.max(startWidth, endWidth, interpolatedWidth)
          * muscleBulgeScale;
        const middle = limbRing(center, bulgeWidth);
        wearStrip(mesh, lower, middle, fill);
        wearStrip(mesh, middle, upper, fill);
      } else {
        wearStrip(mesh, lower, upper, fill);
      }
      wearCap(mesh, lower, fill);
      wearCap(mesh, [...upper].reverse(), fill);
    }

    function wearShoe(mesh, ankle, foot, axes, footScale, fill, knee = null, preferredSide = null) {
      if (!ankle || !foot) return null;
      const worldUp = new THREE.Vector3(0, 1, 0);
      const footVector = foot.clone().sub(ankle);
      const footLength = footVector.length();
      const footForward = footLength > .0001
        ? footVector.multiplyScalar(1 / footLength)
        : wearUnit(axes.forward, new THREE.Vector3(0, 0, 1));
      const shinUp = knee ? knee.clone().sub(ankle) : worldUp;
      const defaultShoeUp = wearUnit(
        shinUp.clone().addScaledVector(footForward, -shinUp.dot(footForward)),
        axes.up
      );
      const fallbackSide = wearUnit(
        axes.side.clone().addScaledVector(footForward, -axes.side.dot(footForward)),
        axes.side
      );
      // Box-ring winding expects side x up to oppose the forward extrusion.
      const footSide = preferredSide
        ? wearUnit(preferredSide.clone().addScaledVector(footForward, -preferredSide.dot(footForward)), fallbackSide)
        : wearUnit(footForward.clone().cross(defaultShoeUp), fallbackSide);
      const shoeUp = wearUnit(footSide.clone().cross(footForward), defaultShoeUp);
      const shoeScale = footLength > .0001 ? footLength : footScale * .60;
      // Shift the shoe backward to enclose the ankle connector.
      const length = shoeScale * 1.15;
      const halfWidth = Math.max(shoeScale * .32, footScale * .18);
      const height = Math.max(shoeScale * .28, footScale * .15);
      const profile = [
        [-.10, -.08, .72, .48],
        [.16, -.02, .82, .58],
        [.38, -.04, .94, .60],
        [.76, -.22, 1.06, .42],
        [1.00, -.30, .90, .30],
      ];
      const rings = profile.map(([forwardScale, upScale, widthScale, heightScale]) => {
        // Offset only the mesh; keep the animated foot joint unchanged.
        const center = foot.clone()
          .addScaledVector(footForward, length * (forwardScale - 1.10))
          .addScaledVector(shoeUp, height * (upScale + .60));
        return wearBoxRing(
          mesh, center, footSide, shoeUp,
          halfWidth * widthScale, height * heightScale
        );
      });
      for (let index = 0; index < rings.length - 1; index += 1) {
        wearStrip(mesh, rings[index], rings[index + 1], fill);
      }
      wearCap(mesh, rings[0], fill);
      wearCap(mesh, [...rings[rings.length - 1]].reverse(), fill);
      // Intersect the shin axis with the shoe's actual upper profile.
      const shinDirection = wearUnit(shinUp.clone(), shoeUp);
      const axisForward = shinDirection.dot(footForward);
      const axisUp = shinDirection.dot(shoeUp);
      let surfaceDistance = null;
      for (let i = 0; i < profile.length - 1; i++) {
        const rear = profile[i], front = profile[i + 1];
        const rearForward = footLength + length * (rear[0] - 1.10);
        const frontForward = footLength + length * (front[0] - 1.10);
        const rearTop = height * (rear[1] + .60 + rear[3]);
        const frontTop = height * (front[1] + .60 + front[3]);
        const slope = (frontTop - rearTop) / (frontForward - rearForward);
        const denominator = axisUp - slope * axisForward;
        if (Math.abs(denominator) > .0001) {
          const distance = (rearTop - slope * rearForward) / denominator;
          const forward = distance * axisForward;
          if (forward >= rearForward && forward <= frontForward) {
            surfaceDistance = Math.max(surfaceDistance ?? distance, distance);
          }
        }
      }
      return ankle.clone().addScaledVector(shinDirection, surfaceDistance ?? 0);
    }

    function wearBuildHumanoid(joints, preferredLimbSides = null, preferredBodyAxes = null) {
      const required = [
        "pelvis", "neck", "head", "left_hip", "right_hip",
        "left_shoulder", "right_shoulder",
      ];
      if (required.some((name) => !joints[name])) return null;
      const primary = "primary";
      const joint = "joint";
      const mesh = wearMeshData();
      const axes = preferredBodyAxes ?? wearAxes(joints);
      const limbSides = wearLimbSides(joints, axes, preferredLimbSides);
      const hipCenter = joints.left_hip.clone().lerp(joints.right_hip, .5);
      if (!wearStableBodyProportions) {
        wearStableBodyProportions = {
          hipWidth: joints.right_hip.distanceTo(joints.left_hip),
          shoulderWidth: joints.right_shoulder.distanceTo(joints.left_shoulder),
        };
      }
      const hipWidth = wearStableBodyProportions.hipWidth;
      const shoulderWidth = wearStableBodyProportions.shoulderWidth;
      const stableSegmentLength = (startName, endName) => {
        if (!joints[startName] || !joints[endName]) return 0;
        const key = `${startName}->${endName}`;
        if (!wearStableSegmentLengths.has(key)) {
          wearStableSegmentLengths.set(
            key,
            joints[startName].distanceTo(joints[endName])
          );
        }
        return wearStableSegmentLengths.get(key);
      };
      const pelvisWidth = Math.max(hipWidth * 1.08, shoulderWidth * .64);
      const footScale = Math.max(hipWidth * .98, shoulderWidth * .58);
      const torsoVector = joints.neck.clone().sub(hipCenter);
      const torsoLength = torsoVector.length();
      const torsoUp = wearUnit(torsoVector, axes.up);
      const waist = joints.spine1
        ?? hipCenter.clone().addScaledVector(torsoUp, torsoLength * .40);
      const shoulderCenter = joints.left_shoulder.clone().lerp(joints.right_shoulder, .5);
      const shoulderSpan = joints.right_shoulder.clone().sub(joints.left_shoulder);
      const shoulderSide = wearUnit(shoulderSpan, axes.side);
      const shoulderUp = wearUnit(
        torsoUp.clone().addScaledVector(shoulderSide, -torsoUp.dot(shoulderSide)), axes.up
      );
      const shoulderAxes = {
        side: shoulderSide,
        up: shoulderUp,
        forward: wearUnit(shoulderSide.clone().cross(shoulderUp), axes.forward),
      };
      // Fit each cap inside the upper arm's narrower (depth) dimension.
      const shoulderCapRadius = side => stableSegmentLength(`${side}_shoulder`, `${side}_elbow`) * .30 * .40;
      // Keep the torso socket height independent of the visible joint cap size.
      const shoulderRadius = (stableSegmentLength("left_shoulder", "left_elbow")
        + stableSegmentLength("right_shoulder", "right_elbow")) * .5 * .30 * .44;
      // Enclose the inner shoulder cap up to its upper hemisphere, as limb
      // segments enclose their joint caps. This is the start of the neck taper.
      const upperChest = shoulderCenter.clone().addScaledVector(shoulderUp, shoulderRadius * .35);
      // Leave room for the traps even when the reconstructed neck is short.
      const neckRise = Math.max(joints.neck.clone().sub(shoulderCenter).dot(shoulderUp), 0);
      const chest = waist.clone().lerp(joints.neck, .45);
      const upperTransitionCenter = joints.neck.clone().addScaledVector(
        shoulderUp, -Math.min(shoulderWidth * .06, neckRise * .20)
      );
      const pelvisUp = wearUnit(waist.clone().sub(hipCenter), torsoUp);
      const hipSide = joints.right_hip.clone().sub(joints.left_hip);
      const pelvisSide = wearUnit(
        hipSide.addScaledVector(pelvisUp, -hipSide.dot(pelvisUp)),
        axes.side
      );
      const pelvisAxes = {
        side: pelvisSide,
        up: pelvisUp,
        forward: wearUnit(pelvisSide.clone().cross(pelvisUp), axes.forward),
      };
      let previousRingAxes = pelvisAxes;
      const waistAxes = wearAlignRingAxes(
        previousRingAxes,
        wearSpineRingAxes(hipCenter, waist, chest, axes)
      );
      previousRingAxes = waistAxes;
      const chestAxes = wearAlignRingAxes(
        previousRingAxes,
        wearSpineRingAxes(waist, chest, upperChest, axes)
      );
      previousRingAxes = chestAxes;
      const upperChestAxes = wearAlignRingAxes(previousRingAxes, shoulderAxes);
      previousRingAxes = upperChestAxes;
      const upperTransitionAxes = upperChestAxes;
      const waistResolvedBackDepth = shoulderWidth * .18;
      const waistRing = wearDirectionalRing(
        mesh, waist, waistAxes.side, waistAxes.forward,
        shoulderWidth * .30, shoulderWidth * .16, waistResolvedBackDepth
      );
      const chestRings = [
        waistRing,
        wearDirectionalRing(
          mesh, chest, chestAxes.side, chestAxes.forward,
          shoulderWidth * .37, shoulderWidth * .18, shoulderWidth * .24, null, .38
        ),
        wearDirectionalRing(
          mesh, upperChest, upperChestAxes.side, upperChestAxes.forward,
          Math.max(joints.left_shoulder.distanceTo(joints.right_shoulder) * .5 - shoulderRadius * .35, .001),
          shoulderWidth * .18, shoulderWidth * .24, null, .38
        ),
      ];
      // Blend corresponding surface vertices toward the socket, with an upright
      // tangent at the join. The transition cannot bulge past either endpoint.
      const upperBackRing = chestRings[1].map((lowerIndex, index) => {
        const lower = mesh.vertices[lowerIndex];
        const upper = mesh.vertices[chestRings[2][index]];
        const rise = Math.max(upper.clone().sub(lower).dot(upperChestAxes.up), 0);
        const control = upper.clone().addScaledVector(upperChestAxes.up, -rise * .5);
        return wearVertex(mesh, lower.clone().lerp(control, .6).lerp(control.clone().lerp(upper, .6), .6));
      });
      chestRings.splice(2, 0, upperBackRing);
      for (let index = 0; index < chestRings.length - 1; index += 1) {
        wearStrip(mesh, chestRings[index], chestRings[index + 1], primary);
      }
      const upperTransitionRing = wearDirectionalRing(
        mesh, upperTransitionCenter, upperTransitionAxes.side, upperTransitionAxes.forward,
        shoulderWidth * .14, shoulderWidth * .105, shoulderWidth * .09, null, .18
      );
      // Continue the upper chest directly into the neck. A second full-width
      // shoulder rim would create a flat shelf beneath the trapezius surface.
      const shoulderRing = chestRings[chestRings.length - 1];
      const trapeziusRing = shoulderRing.map((lowerIndex, index) => {
        const lower = mesh.vertices[lowerIndex];
        const upper = mesh.vertices[upperTransitionRing[index]];
        const rise = Math.max(upper.clone().sub(lower).dot(shoulderUp), 0);
        const control = lower.clone().lerp(upper, .5).addScaledVector(shoulderUp, rise * .25);
        return wearVertex(mesh, lower.clone().lerp(control, .5).lerp(control.clone().lerp(upper, .5), .5));
      });
      wearStrip(mesh, shoulderRing, trapeziusRing, primary);
      wearStrip(mesh, trapeziusRing, upperTransitionRing, primary);
      const neckLowerCenter = upperTransitionCenter;
      const neckLowerRing = upperTransitionRing;
      const neckMidLerp = .55;
      const neckMid = neckLowerCenter.clone().lerp(joints.neck, neckMidLerp);
      const neckMidAxes = wearAlignRingAxes(
        previousRingAxes,
        wearSpineRingAxes(neckLowerCenter, neckMid, joints.neck, shoulderAxes)
      );
      previousRingAxes = neckMidAxes;
      const neckUpperCenter = joints.neck.clone();
      const neckMidHalfWidth = shoulderWidth * .14;
      const neckUpperHalfWidth = shoulderWidth * .115;
      const neckMidRing = wearDirectionalRing(
        mesh, neckMid, neckMidAxes.side, neckMidAxes.forward,
        neckMidHalfWidth, shoulderWidth * .105,
        shoulderWidth * .09
      );
      const neckUpperRing = wearDirectionalRing(
        mesh, neckUpperCenter, neckMidAxes.side, neckMidAxes.forward,
        neckUpperHalfWidth, shoulderWidth * .085,
        shoulderWidth * .075
      );
      wearStrip(mesh, neckLowerRing, neckMidRing, joint);
      wearStrip(mesh, neckMidRing, neckUpperRing, joint);
      const neckMidPoint = joints.neck.clone().lerp(joints.head, .5);
      const headAxes = wearAlignRingAxes(
        previousRingAxes,
        wearSpineRingAxes(joints.neck, neckMidPoint, joints.head, shoulderAxes)
      );

      const pelvisTop = hipCenter.clone().lerp(waist, .76);
      const pelvisMid = hipCenter.clone().lerp(waist, .38);
      const pelvisBottom = hipCenter.clone().lerp(waist, .06);
      const pelvisJunction = pelvisTop.clone().addScaledVector(pelvisAxes.forward, pelvisWidth * .03);
      const pelvisJunctionWidth = wearTorsoBodyWidth(
        hipWidth,
        shoulderWidth,
        wearSpineProgress(hipCenter, joints.neck, pelvisJunction)
      );
      const pelvisMidWidth = wearTorsoBodyWidth(
        hipWidth,
        shoulderWidth,
        wearSpineProgress(hipCenter, joints.neck, pelvisMid)
      );
      const pelvisBackDepth = { value: 0 };
      const pelvisBottomRing = wearTorsoRing(
        mesh, pelvisBottom, pelvisAxes.side, pelvisAxes.forward, hipWidth * .50, hipWidth * .34,
        1.06, .42, .44, 1.08, .14, .56, pelvisBackDepth
      );
      const pelvisMidRing = wearTorsoRing(
        mesh, pelvisMid, pelvisAxes.side, pelvisAxes.forward, pelvisMidWidth * .52, pelvisMidWidth * .36,
        1.08, .40, .48, 1.14, .12, .54, pelvisBackDepth
      );
      pelvisBackDepth.value = Math.max(pelvisBackDepth.value, waistResolvedBackDepth * 0.96);
      const pelvisJunctionRing = wearTorsoRing(
        mesh, pelvisJunction, pelvisAxes.side, pelvisAxes.forward, pelvisJunctionWidth * .50, pelvisJunctionWidth * .30,
        1.10, .36, .42, 1.10, .14, .62, pelvisBackDepth
      );
      const pelvisRings = [pelvisJunctionRing, pelvisMidRing, pelvisBottomRing];
      wearStrip(mesh, pelvisRings[2], pelvisRings[1], primary);
      wearStrip(mesh, pelvisRings[1], pelvisRings[0], primary);
      wearCap(mesh, pelvisRings[2], primary);
      wearStrip(mesh, pelvisRings[0], chestRings[0], primary);

      const segmentWidth = (startName, endName, scale) =>
        stableSegmentLength(startName, endName) * scale;
      wearSphere(mesh, joints.left_hip, axes, segmentWidth("left_hip", "left_knee", .27) * .48, joint);
      wearSphere(mesh, joints.right_hip, axes, segmentWidth("right_hip", "right_knee", .27) * .48, joint);
      for (const side of ["left", "right"]) {
        wearSphere(mesh, joints[`${side}_shoulder`], upperChestAxes, shoulderCapRadius(side), joint);
      }

      const headHeightAtJoint = stableSegmentLength("neck", "head");
      if (headHeightAtJoint > .0001) {
        const headHeight = Math.max(headHeightAtJoint * 1.65, shoulderWidth * .45);
        const headWidth = Math.max(headHeightAtJoint * 1.08, shoulderWidth * .37);
        const headDepth = headWidth * .82;
        const base = joints.neck.clone().addScaledVector(headAxes.up, headHeight * .02);
        const center = base.clone().addScaledVector(headAxes.up, headHeight * .44);
        const rings = [
          wearBoxRing(
            mesh, base, headAxes.side, headAxes.forward,
            shoulderWidth * .12, shoulderWidth * .08
          ),
          wearBoxRing(mesh, center, headAxes.side, headAxes.forward, headWidth * .52, headDepth * .52),
          wearBoxRing(mesh, base.clone().addScaledVector(headAxes.up, headHeight), headAxes.side, headAxes.forward, headWidth * .44, headDepth * .44),
        ];
        wearStrip(mesh, neckUpperRing, rings[0], primary);
        wearStrip(mesh, rings[0], rings[1], primary);
        wearStrip(mesh, rings[1], rings[2], primary);
        wearCap(mesh, [...rings[2]].reverse(), primary);
      }

      for (const [
        startName, endName, startWidth, endWidth, depthScale,
        muscleBulgeScale, muscleBulgePosition,
      ] of wearLimbs) {
        if (!joints[startName] || !joints[endName]) continue;
        const segmentLength = stableSegmentLength(startName, endName);
        const scaledStartWidth = segmentLength * startWidth;
        const scaledEndWidth = segmentLength * endWidth;
        wearSegment(
          mesh, joints[startName], joints[endName], axes,
          scaledStartWidth, scaledEndWidth, depthScale, primary,
          wearClearance(startName, scaledStartWidth),
          wearClearance(endName, scaledEndWidth),
          limbSides.get(`${startName}->${endName}`),
          muscleBulgeScale,
          muscleBulgePosition
        );
      }
      const addHand = (wristName, handName, elbowName) => {
        const wrist = joints[wristName];
        const hand = joints[handName];
        if (!wrist || !hand) return;
        const handLength = stableSegmentLength(wristName, handName);
        const wristWidth = Math.max(
          segmentWidth(elbowName, wristName, .17) * .90,
          handLength * .42
        );
        const palmWidth = Math.max(wristWidth * 1.10, handLength * .50);
        wearSegment(
          mesh, wrist, hand, axes,
          wristWidth, palmWidth * .90, .36, primary,
          wearClearance(wristName, wristWidth), 0, null,
          1.12, .58
        );
      };
      addHand("left_wrist", "left_hand", "left_elbow");
      addHand("right_wrist", "right_hand", "right_elbow");
      const leftFootSurface = wearShoe(mesh, joints.left_ankle, joints.left_foot, axes, footScale, primary,
        joints.left_knee, limbSides.get("left_ankle->left_foot"));
      const rightFootSurface = wearShoe(mesh, joints.right_ankle, joints.right_foot, axes, footScale, primary,
        joints.right_knee, limbSides.get("right_ankle->right_foot"));
      const ankleCapCenter = (kneeName, ankleName, footSurface) => {
        const knee = joints[kneeName];
        const ankle = joints[ankleName];
        if (!knee || !ankle) return ankle;
        const shin = ankle.clone().sub(knee);
        const shinLength = shin.length();
        if (shinLength <= .0001) return ankle;
        const endWidth = segmentWidth(kneeName, ankleName, .165);
        const clearance = Math.min(wearClearance(ankleName, endWidth), shinLength * .15);
        const shinEnd = ankle.clone().addScaledVector(shin.multiplyScalar(1 / shinLength), -clearance);
        return shinEnd.lerp(footSurface ?? ankle, .5);
      };
      if (joints.left_elbow) wearSphere(mesh, joints.left_elbow, axes, Math.max(
        segmentWidth("left_shoulder", "left_elbow", .225),
        segmentWidth("left_elbow", "left_wrist", .235)
      ) * .40, joint);
      if (joints.right_elbow) wearSphere(mesh, joints.right_elbow, axes, Math.max(
        segmentWidth("right_shoulder", "right_elbow", .225),
        segmentWidth("right_elbow", "right_wrist", .235)
      ) * .40, joint);
      if (joints.left_wrist) wearSphere(
        mesh, joints.left_wrist, axes,
        segmentWidth("left_elbow", "left_wrist", .17) * .30,
        joint
      );
      if (joints.right_wrist) wearSphere(
        mesh, joints.right_wrist, axes,
        segmentWidth("right_elbow", "right_wrist", .17) * .30,
        joint
      );
      if (joints.left_knee) wearSphere(mesh, joints.left_knee, axes, Math.max(
        segmentWidth("left_hip", "left_knee", .215),
        segmentWidth("left_knee", "left_ankle", .225)
      ) * .40, joint);
      if (joints.right_knee) wearSphere(mesh, joints.right_knee, axes, Math.max(
        segmentWidth("right_hip", "right_knee", .215),
        segmentWidth("right_knee", "right_ankle", .225)
      ) * .40, joint);
      if (joints.left_ankle) wearSphere(
        mesh,
        ankleCapCenter("left_knee", "left_ankle", leftFootSurface),
        axes,
        segmentWidth("left_knee", "left_ankle", .165) * .50,
        joint
      );
      if (joints.right_ankle) wearSphere(
        mesh,
        ankleCapCenter("right_knee", "right_ankle", rightFootSurface),
        axes,
        segmentWidth("right_knee", "right_ankle", .165) * .50,
        joint
      );
      return mesh;
    }

    function wearColor(hex, lightLevel) {
      const value = Number.parseInt(hex.replace("#", ""), 16);
      return new THREE.Color().setRGB(
        ((value >> 16) & 255) / 255 * lightLevel,
        ((value >> 8) & 255) / 255 * lightLevel,
        (value & 255) / 255 * lightLevel,
        THREE.SRGBColorSpace
      );
    }

    function wearApplyExportedSoleSides(frame, sides) {
      for (const side of ["left", "right"]) {
        const key = `${side}_ankle->${side}_foot`;
        const exported = frame.boneSides?.[key];
        if (exported) sides.set(key, new THREE.Vector3(...exported));
      }
    }

    function updateWearExactMesh(frame, frameTranslation) {
      if (wearStableFrames !== playbackState.frames) {
        wearStableFrames = playbackState.frames;
        wearStableSidesByFrame = null;
        wearStableBodyAxesByFrame = null;
      }
      const joints = {};
      for (const [name, point] of Object.entries(frame.joints)) {
        joints[name] = toWorldPoint(point, frameTranslation, fixedRoot, true, name);
      }
      if (!wearStableSidesByFrame) {
        wearStableSidesByFrame = wearBuildStableSidesByFrame();
      }
      if (!wearStableBodyAxesByFrame) {
        wearStableBodyAxesByFrame = wearBuildStableBodyAxesByFrame();
      }
      const resolvedFrameIndex = frame.playbackIndex ?? playbackState.frames.indexOf(frame);
      const stableSides = new Map(wearStableSidesByFrame[resolvedFrameIndex] ?? []);
      const nextSides = wearStableSidesByFrame[frame.playbackNextIndex];
      if (nextSides && frame.playbackAlpha > 0) {
        for (const [key, side] of stableSides) {
          const next = nextSides.get(key);
          if (next) stableSides.set(key, side.clone().lerp(next, frame.playbackAlpha).normalize());
        }
      }
      for (const side of ["left", "right"]) {
        const start = `${side}_elbow`, end = `${side}_wrist`, key = `${start}->${end}`;
        const exported = frame.boneSides?.[key];
        const reference = exported ? new THREE.Vector3(...exported)
          : smplBoneCrossSectionReference(frame, start, end, frameTranslation);
        if (reference) stableSides.set(key, reference);
      }
      wearApplyExportedSoleSides(frame, stableSides);
      const stableBodyAxes = wearStableBodyAxesByFrame[resolvedFrameIndex] ?? null;
      const generated = wearBuildHumanoid(joints, stableSides, stableBodyAxes);
      if (!generated) {
        wearExactMesh.visible = false;
        return;
      }
      const appearance = wearHumanoidGeometry.appearance ?? {};
      const ambientLight = Number(appearance.ambientLightLevel ?? .38);
      const keyLightStrength = Number(appearance.keyLightStrength ?? .48);
      const fillLightStrength = Number(appearance.fillLightStrength ?? .14);
      const hemisphereLightStrength = Number(appearance.hemisphereLightStrength ?? .10);
      const yaw = (
        Number(wearHumanoidGeometry.view?.yawDegrees ?? -28)
        + Number(appearance.keyLightYawOffsetDegrees ?? -25)
      ) * Math.PI / 180;
      const elevation = Number(appearance.keyLightElevationDegrees ?? 50) * Math.PI / 180;
      const keyDirection = new THREE.Vector3(
        Math.sin(yaw) * Math.cos(elevation),
        Math.sin(elevation),
        Math.cos(yaw) * Math.cos(elevation)
      ).normalize();
      const fillDirection = new THREE.Vector3(
        -keyDirection.x,
        Math.abs(keyDirection.y) * .35,
        -keyDirection.z
      ).normalize();
      const positions = [];
      const colors = [];
      for (const face of generated.faces) {
        const points = face.indices.map((index) => generated.vertices[index]);
        if (points.length < 3) continue;
        const normal = wearUnit(
          points[1].clone().sub(points[0]).cross(points[2].clone().sub(points[1])),
          new THREE.Vector3(0, 1, 0)
        );
        const keyDiffuse = Math.max(0, Math.min(1, normal.dot(keyDirection)));
        const fillDiffuse = Math.max(0, Math.min(1, normal.dot(fillDirection)));
        const upperHemisphere = Math.max(0, Math.min(1, normal.y * .5 + .5));
        const level = Math.max(0, Math.min(1,
          ambientLight
          + keyDiffuse * keyLightStrength
          + fillDiffuse * fillLightStrength
          + upperHemisphere * hemisphereLightStrength
        ));
        const color = wearColor(
          face.fill === "joint"
            ? appearance.jointFill ?? "#5a5a5a"
            : appearance.primaryFill ?? "#fe6a07",
          level
        );
        for (let index = 1; index < points.length - 1; index += 1) {
          for (const point of [points[0], points[index], points[index + 1]]) {
            positions.push(point.x, point.y, point.z);
            colors.push(color.r, color.g, color.b);
          }
        }
      }
      wearExactGeometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(positions, 3)
      );
      wearExactGeometry.setAttribute(
        "color",
        new THREE.Float32BufferAttribute(colors, 3)
      );
      wearExactGeometry.computeBoundingSphere();
      wearExactMesh.visible = true;
    }
