#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;
layout(location = 1) out vec2 sceneCoord;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 rigSize;
    vec2 nativeSize;
    vec2 shoulderPivot;
    vec2 elbowPivot;
    vec2 wristPivot;
    vec2 gloveContactPivot;
    float shoulderAngle;
    float elbowAngle;
    float wristAngle;
    float forearmStretch;
    float gloveBendRadians;
    float upperArmFlexNativePx;
    float delayedClothTipAngle;
} ubuf;

layout(binding = 2) uniform sampler2D weights;
layout(binding = 3) uniform sampler2D clothTipWeight;

mat3 translateBy(vec2 offset)
{
    return mat3(1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                offset.x, offset.y, 1.0);
}

mat3 rotateAround(vec2 pivot, float angle)
{
    float cosine = cos(angle);
    float sine = sin(angle);
    mat3 rotation = mat3(cosine, sine, 0.0,
                         -sine, cosine, 0.0,
                         0.0, 0.0, 1.0);
    return translateBy(pivot) * rotation * translateBy(-pivot);
}

mat3 scaleAlongAround(vec2 pivot, vec2 axis, float amount)
{
    vec2 tangent = normalize(axis);
    vec2 normal = vec2(-tangent.y, tangent.x);
    // Preserve projected volume through the forearm. The separate cuff bridge
    // below converges this transform to the rigid glove before the wrist seam.
    float normalAmount = pow(max(amount, 0.001), -0.6);
    mat2 stretch = mat2(
        amount * tangent.x * tangent.x + normalAmount * normal.x * normal.x,
        amount * tangent.x * tangent.y + normalAmount * normal.x * normal.y,
        amount * tangent.x * tangent.y + normalAmount * normal.x * normal.y,
        amount * tangent.y * tangent.y + normalAmount * normal.y * normal.y);
    vec2 translation = pivot - stretch * pivot;
    return mat3(
        stretch[0][0], stretch[0][1], 0.0,
        stretch[1][0], stretch[1][1], 0.0,
        translation.x, translation.y, 1.0);
}

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    vec2 sourcePoint = qt_MultiTexCoord0 * ubuf.nativeSize;
    vec3 sourceHomogeneous = vec3(sourcePoint, 1.0);
    vec2 upperArmStart = ubuf.shoulderPivot * ubuf.nativeSize;
    vec2 upperArmVector = (ubuf.elbowPivot - ubuf.shoulderPivot) * ubuf.nativeSize;
    float upperArmLength = max(length(upperArmVector), 0.0001);
    vec2 upperArmTangent = upperArmVector / upperArmLength;
    vec2 upperArmNormal = vec2(-upperArmTangent.y, upperArmTangent.x);
    float upperArmT = clamp(
        dot(sourcePoint - upperArmStart, upperArmTangent) / upperArmLength,
        0.0, 1.0);
    float upperArmOneMinusT = 1.0 - upperArmT;
    float upperArmEnvelope = 16.0 * upperArmT * upperArmT
                           * upperArmOneMinusT * upperArmOneMinusT;
    vec2 flexedShoulderPoint = sourcePoint + upperArmNormal
        * ubuf.upperArmFlexNativePx * upperArmEnvelope;

    mat3 shoulderTransform = rotateAround(
        ubuf.shoulderPivot * ubuf.nativeSize, ubuf.shoulderAngle);
    vec2 elbowNative = ubuf.elbowPivot * ubuf.nativeSize;
    vec2 wristNative = ubuf.wristPivot * ubuf.nativeSize;
    vec2 restForearmAxis = wristNative - elbowNative;
    mat3 forearmTransform = shoulderTransform * rotateAround(
        elbowNative, ubuf.elbowAngle) * scaleAlongAround(
        elbowNative, restForearmAxis, ubuf.forearmStretch);
    vec2 posedWristNative = (
        forearmTransform * vec3(wristNative, 1.0)).xy;
    mat3 gloveRigidTransform = translateBy(
        posedWristNative - wristNative) * rotateAround(
        wristNative,
        ubuf.shoulderAngle + ubuf.elbowAngle + ubuf.wristAngle);
    mat3 gloveTransform = gloveRigidTransform * rotateAround(
        ubuf.gloveContactPivot * ubuf.nativeSize,
        ubuf.gloveBendRadians);
    mat3 clothTipTransform = gloveTransform * rotateAround(
        ubuf.gloveContactPivot * ubuf.nativeSize,
        ubuf.delayedClothTipAngle);

    vec3 baseWeights = texture(weights, qt_MultiTexCoord0).rgb;
    float baseWeightSum = dot(baseWeights, vec3(1.0));
    float activeBaseChannels = dot(
        step(vec3(0.5 / 255.0), baseWeights), vec3(1.0));
    bool baseTransition = activeBaseChannels > 1.5;
    vec3 unitBaseWeights = vec3(0.0);
    if (baseWeightSum > 0.0001) {
        if (baseTransition) {
            unitBaseWeights = baseWeights / baseWeightSum;
        } else {
            float dominantWeight = max(
                baseWeights.r, max(baseWeights.g, baseWeights.b));
            unitBaseWeights = step(
                vec3(dominantWeight - 0.5 / 255.0), baseWeights);
        }
    }
    float deformationGain = baseWeightSum > 0.0001 ? 1.0 : 0.0;
    float clothInfluence = clamp(
        texture(clothTipWeight, qt_MultiTexCoord0).r * deformationGain,
        0.0, 1.0);
    vec4 skinWeights = vec4(unitBaseWeights * (1.0 - clothInfluence),
                            clothInfluence);
    float totalInfluence = dot(skinWeights, vec4(1.0));
    if (baseTransition) {
        skinWeights /= max(totalInfluence, 0.0001);
    }

    vec2 posedPoint = sourcePoint;
    if (totalInfluence > 0.0001) {
        vec2 forearmPosedPoint =
            (forearmTransform * sourceHomogeneous).xy;
        vec2 glovePosedPoint =
            (gloveTransform * sourceHomogeneous).xy;
        float forearmLength = max(length(restForearmAxis), 0.001);
        float axialProjection = dot(
            sourcePoint - elbowNative,
            normalize(restForearmAxis)) / forearmLength;
        float cuffBridge = smoothstep(0.84, 1.0, axialProjection);
        vec2 connectedForearmPoint = mix(
            forearmPosedPoint, glovePosedPoint, cuffBridge);
        vec2 fullyPosedPoint =
              skinWeights.r * (shoulderTransform * vec3(flexedShoulderPoint, 1.0)).xy
            + skinWeights.g * connectedForearmPoint
            + skinWeights.b * glovePosedPoint
            + skinWeights.a * (clothTipTransform * sourceHomogeneous).xy;
        posedPoint = mix(sourcePoint, fullyPosedPoint, deformationGain);
    }

    vec2 displacement = (posedPoint - sourcePoint)
                      * ubuf.rigSize / ubuf.nativeSize;
    vec4 displacedVertex = qt_Vertex;
    displacedVertex.xy += displacement;
    sceneCoord = displacedVertex.xy / max(ubuf.rigSize, vec2(1.0));
    gl_Position = ubuf.qt_Matrix * displacedVertex;
}
