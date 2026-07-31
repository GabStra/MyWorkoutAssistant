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

    const wearLimbs = [
      ["left_hip", "left_knee", .25, .205, .44, 1.16, .42],
      ["left_knee", "left_ankle", .215, .16, .42, 1.12, .46],
      ["right_hip", "right_knee", .25, .205, .44, 1.16, .42],
      ["right_knee", "right_ankle", .215, .16, .42, 1.12, .46],
      ["left_shoulder", "left_elbow", .27, .215, .42, 1.18, .48],
      ["left_elbow", "left_wrist", .225, .17, .40, 1.10, .40],
      ["right_shoulder", "right_elbow", .27, .215, .42, 1.18, .48],
      ["right_elbow", "right_wrist", .225, .17, .40, 1.10, .40],
    ];
    const wearCapNames = new Set([
      "left_hip", "right_hip", "left_shoulder", "right_shoulder",
      "left_elbow", "right_elbow", "left_wrist", "right_wrist",
      "left_knee", "right_knee",
      "left_ankle", "right_ankle",
    ]);
    let wearPreviousSides = new Map();

    function wearUnit(vector, fallback) {
      return vector.lengthSq() > 1e-8 ? vector.normalize() : fallback.clone();
    }

    function wearAxes(joints) {
      const hipSide = joints.left_hip && joints.right_hip
        ? joints.right_hip.clone().sub(joints.left_hip)
        : new THREE.Vector3(1, 0, 0);
      const shoulderSide = joints.left_shoulder && joints.right_shoulder
        ? joints.right_shoulder.clone().sub(joints.left_shoulder)
        : hipSide.clone();
      const side = wearUnit(hipSide.add(shoulderSide), new THREE.Vector3(1, 0, 0));
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

    function wearLimbSides(joints, axes) {
      const current = new Map();
      for (const [startName, endName] of wearLimbs) {
        if (!joints[startName] || !joints[endName]) continue;
        const direction = joints[endName].clone().sub(joints[startName]);
        if (direction.lengthSq() <= 1e-8) continue;
        direction.normalize();
        const key = `${startName}->${endName}`;
        const previous = wearPreviousSides.get(key);
        let side;
        if (previous) {
          const transported = previous.clone().addScaledVector(direction, -previous.dot(direction));
          side = transported.lengthSq() > 1e-8
            ? transported.normalize()
            : wearStableSide(direction, axes);
          if (side.dot(previous) < 0) side.multiplyScalar(-1);
        } else {
          side = wearStableSide(direction, axes);
        }
        current.set(key, side);
      }
      wearPreviousSides = current;
      return current;
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

    function wearDirectionalRing(mesh, center, side, depth, halfWidth, frontDepth, backDepth) {
      return [
        center.clone().addScaledVector(side, halfWidth).addScaledVector(depth, frontDepth),
        center.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, frontDepth),
        center.clone().addScaledVector(side, -halfWidth).addScaledVector(depth, -backDepth),
        center.clone().addScaledVector(side, halfWidth).addScaledVector(depth, -backDepth),
      ].map((point) => wearVertex(mesh, point));
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
      const count = Math.min(lower.length, upper.length);
      for (let index = 0; index < count; index += 1) {
        const next = (index + 1) % count;
        wearFace(mesh, [lower[index], upper[index], upper[next], lower[next]], fill);
      }
    }

    function wearCap(mesh, ring, fill) {
      if (ring.length >= 3) wearFace(mesh, ring, fill);
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
      if (name.includes("hip")) return width * .46;
      if (name.includes("shoulder")) return width * .32;
      if (name.includes("ankle")) return width * .44;
      return width * .20;
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
      const maxInset = length * .10;
      const safeStart = start.clone().addScaledVector(direction, Math.min(startInset, maxInset));
      const safeEnd = end.clone().addScaledVector(direction, -Math.min(endInset, maxInset));
      if (safeEnd.distanceToSquared(safeStart) <= 1e-8) return;
      const projected = preferredSide
        ? preferredSide.clone().addScaledVector(direction, -preferredSide.dot(direction))
        : wearStableSide(direction, axes);
      const side = wearUnit(projected, wearStableSide(direction, axes));
      const depth = wearUnit(side.clone().cross(direction), axes.forward);
      const lower = wearBoxRing(
        mesh, safeStart, side, depth, startWidth * .5, startWidth * depthScale
      );
      const upper = wearBoxRing(
        mesh, safeEnd, side, depth, endWidth * .5, endWidth * depthScale
      );
      if (muscleBulgeScale > 1) {
        const position = Math.max(.2, Math.min(.8, muscleBulgePosition));
        const center = safeStart.clone().lerp(safeEnd, position);
        const interpolatedWidth = startWidth + (endWidth - startWidth) * position;
        const bulgeWidth = Math.max(startWidth, endWidth, interpolatedWidth)
          * muscleBulgeScale;
        const middle = wearBoxRing(
          mesh, center, side, depth, bulgeWidth * .5, bulgeWidth * depthScale
        );
        wearStrip(mesh, lower, middle, fill);
        wearStrip(mesh, middle, upper, fill);
      } else {
        wearStrip(mesh, lower, upper, fill);
      }
      wearCap(mesh, lower, fill);
      wearCap(mesh, [...upper].reverse(), fill);
    }

    function wearShoe(mesh, ankle, foot, axes, footScale, fill) {
      if (!ankle || !foot) return false;
      const worldUp = new THREE.Vector3(0, 1, 0);
      const footVector = foot.clone().sub(ankle);
      const horizontal = footVector.clone().addScaledVector(worldUp, -footVector.dot(worldUp));
      const horizontalLength = horizontal.length();
      const bodyForward = axes.forward.clone().addScaledVector(worldUp, -axes.forward.dot(worldUp));
      const footForward = horizontalLength > .0001
        ? horizontal.multiplyScalar(1 / horizontalLength)
        : wearUnit(bodyForward, new THREE.Vector3(0, 0, 1));
      const fallbackSide = wearUnit(
        axes.side.clone().addScaledVector(worldUp, -axes.side.dot(worldUp)),
        axes.side
      );
      // Box-ring winding expects side x up to oppose the forward extrusion.
      const footSide = wearUnit(footForward.clone().cross(worldUp), fallbackSide);
      const shoeScale = horizontalLength > .0001 ? horizontalLength : footScale * .60;
      const length = Math.max(shoeScale * 1.45, footScale * .58);
      const halfWidth = Math.max(shoeScale * .32, footScale * .18);
      const height = Math.max(shoeScale * .28, footScale * .15);
      const profile = [
        [-.02, -.08, .72, .48],
        [.16, -.02, .82, .58],
        [.38, -.04, .94, .60],
        [.76, -.22, 1.06, .42],
        [1.00, -.30, .90, .30],
      ];
      const rings = profile.map(([forwardScale, upScale, widthScale, heightScale]) => {
        const center = ankle.clone()
          .addScaledVector(footForward, length * forwardScale)
          .addScaledVector(worldUp, height * upScale);
        return wearBoxRing(
          mesh, center, footSide, worldUp,
          halfWidth * widthScale, height * heightScale
        );
      });
      for (let index = 0; index < rings.length - 1; index += 1) {
        wearStrip(mesh, rings[index], rings[index + 1], fill);
      }
      wearCap(mesh, rings[0], fill);
      wearCap(mesh, [...rings[rings.length - 1]].reverse(), fill);
      return true;
    }

    function wearBuildHumanoid(joints) {
      const required = [
        "pelvis", "neck", "head", "left_hip", "right_hip",
        "left_shoulder", "right_shoulder",
      ];
      if (required.some((name) => !joints[name])) return null;
      const primary = "primary";
      const joint = "joint";
      const mesh = wearMeshData();
      const axes = wearAxes(joints);
      const limbSides = wearLimbSides(joints, axes);
      const hipCenter = joints.left_hip.clone().lerp(joints.right_hip, .5);
      const shoulderCenter = joints.left_shoulder.clone().lerp(joints.right_shoulder, .5);
      const hipWidth = joints.right_hip.distanceTo(joints.left_hip);
      const shoulderWidth = joints.right_shoulder.distanceTo(joints.left_shoulder);
      const pelvisWidth = Math.max(hipWidth * 1.08, shoulderWidth * .64);
      const footScale = Math.max(hipWidth * .98, shoulderWidth * .58);
      const torsoVector = joints.neck.clone().sub(hipCenter);
      const torsoLength = torsoVector.length();
      const torsoUp = wearUnit(torsoVector, axes.up);
      const chestForward = axes.forward.clone().multiplyScalar(shoulderWidth * .04);
      const waist = joints.spine1
        ?? hipCenter.clone().addScaledVector(torsoUp, torsoLength * .40);
      const chest = joints.spine2
        ?? hipCenter.clone().addScaledVector(torsoUp, torsoLength * .60);
      const upperChest = joints.spine3
        ?? chest.clone().lerp(joints.neck, .52);
      const chestTop = shoulderCenter.clone().lerp(joints.neck, .04).add(chestForward);
      const waistAxes = wearSpineRingAxes(hipCenter, waist, chest, axes);
      const chestAxes = wearSpineRingAxes(waist, chest, upperChest, axes);
      const upperChestAxes = wearSpineRingAxes(chest, upperChest, chestTop, axes);
      const chestTopAxes = wearSpineRingAxes(upperChest, chestTop, joints.neck, axes);
      const chestRings = [
        wearBoxRing(mesh, waist, waistAxes.side, waistAxes.forward, shoulderWidth * .28, shoulderWidth * .14),
        wearBoxRing(mesh, chest, chestAxes.side, chestAxes.forward, shoulderWidth * .34, shoulderWidth * .16),
        wearBoxRing(mesh, upperChest, upperChestAxes.side, upperChestAxes.forward, shoulderWidth * .43, shoulderWidth * .19),
        wearBoxRing(mesh, chestTop, chestTopAxes.side, chestTopAxes.forward, shoulderWidth * .49, shoulderWidth * .20),
      ];
      for (let index = 0; index < chestRings.length - 1; index += 1) {
        wearStrip(mesh, chestRings[index], chestRings[index + 1], primary);
      }
      const trapeziusTop = chestTop.clone().lerp(joints.neck, .38);
      const trapeziusTopRing = wearBoxRing(
        mesh, trapeziusTop, axes.side, axes.forward,
        shoulderWidth * .18, shoulderWidth * .13
      );
      wearStrip(mesh, chestRings[chestRings.length - 1], trapeziusTopRing, primary);

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
      const pelvisTop = hipCenter.clone().lerp(waist, .78);
      const pelvisMid = hipCenter.clone().lerp(waist, .42);
      const pelvisBottom = hipCenter.clone().lerp(waist, .06);
      const pelvisJunction = pelvisTop.clone().addScaledVector(pelvisAxes.forward, pelvisWidth * .03);
      const pelvisRings = [
        wearDirectionalRing(mesh, pelvisJunction, pelvisAxes.side, pelvisAxes.forward, pelvisWidth * .44, pelvisWidth * .31, pelvisWidth * .23),
        wearDirectionalRing(mesh, pelvisMid, pelvisAxes.side, pelvisAxes.forward, pelvisWidth * .56, pelvisWidth * .44, pelvisWidth * .28),
        wearDirectionalRing(mesh, pelvisBottom, pelvisAxes.side, pelvisAxes.forward, pelvisWidth * .40, pelvisWidth * .29, pelvisWidth * .23),
      ];
      wearStrip(mesh, pelvisRings[2], pelvisRings[1], primary);
      wearStrip(mesh, pelvisRings[1], pelvisRings[0], primary);
      wearCap(mesh, pelvisRings[2], primary);
      wearStrip(mesh, pelvisRings[0], chestRings[0], primary);

      const segmentWidth = (startName, endName, scale) => (
        joints[startName] && joints[endName]
          ? joints[startName].distanceTo(joints[endName]) * scale
          : 0
      );
      wearSphere(mesh, joints.neck, axes, shoulderWidth * .10, joint);
      wearSphere(mesh, joints.left_hip, axes, segmentWidth("left_hip", "left_knee", .25) * .56, joint);
      wearSphere(mesh, joints.right_hip, axes, segmentWidth("right_hip", "right_knee", .25) * .56, joint);
      wearSphere(mesh, joints.left_shoulder, axes, segmentWidth("left_shoulder", "left_elbow", .27) * .52, joint);
      wearSphere(mesh, joints.right_shoulder, axes, segmentWidth("right_shoulder", "right_elbow", .27) * .52, joint);

      const neckSpan = joints.neck.clone().sub(trapeziusTop);
      const neckHeight = Math.max(torsoLength * .10, shoulderWidth * .22, neckSpan.length() * 1.25);
      const neckLower = wearBoxRing(mesh, trapeziusTop, axes.side, axes.forward, shoulderWidth * .18, shoulderWidth * .13);
      const neckUpper = wearBoxRing(mesh, joints.neck.clone().addScaledVector(axes.up, neckHeight * .26), axes.side, axes.forward, shoulderWidth * .095, shoulderWidth * .070);
      wearStrip(mesh, neckLower, neckUpper, joint);
      wearCap(mesh, [...neckUpper].reverse(), joint);

      const headHeightAtJoint = joints.head.distanceTo(joints.neck);
      if (headHeightAtJoint > .0001) {
        const headHeight = Math.max(headHeightAtJoint * 1.65, shoulderWidth * .45);
        const headWidth = Math.max(headHeightAtJoint * 1.08, shoulderWidth * .37);
        const headDepth = headWidth * .82;
        const base = joints.neck.clone().addScaledVector(axes.up, headHeight * .06);
        const center = base.clone().addScaledVector(axes.up, headHeight * .44);
        const rings = [
          wearBoxRing(mesh, base, axes.side, axes.forward, headWidth * .34, headDepth * .34),
          wearBoxRing(mesh, center, axes.side, axes.forward, headWidth * .52, headDepth * .52),
          wearBoxRing(mesh, base.clone().addScaledVector(axes.up, headHeight), axes.side, axes.forward, headWidth * .44, headDepth * .44),
        ];
        wearStrip(mesh, rings[0], rings[1], primary);
        wearStrip(mesh, rings[1], rings[2], primary);
        wearCap(mesh, rings[0], primary);
        wearCap(mesh, [...rings[2]].reverse(), primary);
      }

      for (const [
        startName, endName, startWidth, endWidth, depthScale,
        muscleBulgeScale, muscleBulgePosition,
      ] of wearLimbs) {
        if (!joints[startName] || !joints[endName]) continue;
        const segmentLength = joints[startName].distanceTo(joints[endName]);
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
        const handLength = wrist.distanceTo(hand);
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
      const leftShoe = wearShoe(mesh, joints.left_ankle, joints.left_foot, axes, footScale, primary);
      const rightShoe = wearShoe(mesh, joints.right_ankle, joints.right_foot, axes, footScale, primary);
      if (joints.left_elbow) wearSphere(mesh, joints.left_elbow, axes, Math.max(
        segmentWidth("left_shoulder", "left_elbow", .215),
        segmentWidth("left_elbow", "left_wrist", .225)
      ) * .48, joint);
      if (joints.right_elbow) wearSphere(mesh, joints.right_elbow, axes, Math.max(
        segmentWidth("right_shoulder", "right_elbow", .215),
        segmentWidth("right_elbow", "right_wrist", .225)
      ) * .48, joint);
      if (joints.left_wrist) wearSphere(
        mesh, joints.left_wrist, axes,
        segmentWidth("left_elbow", "left_wrist", .17) * .48,
        joint
      );
      if (joints.right_wrist) wearSphere(
        mesh, joints.right_wrist, axes,
        segmentWidth("right_elbow", "right_wrist", .17) * .48,
        joint
      );
      if (joints.left_knee) wearSphere(mesh, joints.left_knee, axes, Math.max(
        segmentWidth("left_hip", "left_knee", .205),
        segmentWidth("left_knee", "left_ankle", .215)
      ) * .48, joint);
      if (joints.right_knee) wearSphere(mesh, joints.right_knee, axes, Math.max(
        segmentWidth("right_hip", "right_knee", .205),
        segmentWidth("right_knee", "right_ankle", .215)
      ) * .48, joint);
      if (joints.left_ankle) wearSphere(
        mesh, joints.left_ankle, axes,
        segmentWidth("left_knee", "left_ankle", .16) * (leftShoe ? .42 : .52),
        joint
      );
      if (joints.right_ankle) wearSphere(
        mesh, joints.right_ankle, axes,
        segmentWidth("right_knee", "right_ankle", .16) * (rightShoe ? .42 : .52),
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

    function updateWearExactMesh(frame, frameTranslation) {
      const joints = {};
      for (const [name, point] of Object.entries(frame.joints)) {
        joints[name] = toWorldPoint(point, frameTranslation, fixedRoot, true, name);
      }
      const generated = wearBuildHumanoid(joints);
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
