#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    vec2 dropCenter;
    vec2 dropExtent;
    vec2 dropRotation;
    float refraction;
    float opticalDensity;
    float atlasIndex;
    float useDropAtlas;
} ubuf;

layout(binding = 1) uniform sampler2D sceneSource;
layout(binding = 2) uniform sampler2D keepoutMask;
layout(binding = 3) uniform sampler2D dropAtlas;
layout(binding = 4) uniform sampler2D dropNormalAtlas;
layout(binding = 5) uniform sampler2D sharpHalo;
layout(binding = 6) uniform sampler2D sharpHaloNormal;

vec2 rotateDropVector(vec2 localVector)
{
    return vec2(
        ubuf.dropRotation.x * localVector.x
            - ubuf.dropRotation.y * localVector.y,
        ubuf.dropRotation.y * localVector.x
            + ubuf.dropRotation.x * localVector.y
    );
}

void main()
{
    vec2 uv = clamp(qt_TexCoord0, vec2(0.0), vec2(1.0));
    vec4 materialColor;
    vec4 packedNormal;

    if (ubuf.useDropAtlas > 0.5) {
        // Invalid/missing randomframe state must never fall through to tile 0.
        if (ubuf.atlasIndex < 0.0 || ubuf.atlasIndex >= 16.0) {
            fragColor = vec4(0.0);
            return;
        }
        float selectedFrame = floor(ubuf.atlasIndex + 0.5);
        vec2 atlasCell = vec2(mod(selectedFrame, 4.0),
                              floor(selectedFrame / 4.0));
        vec2 atlasCellSize = vec2(0.25);
        vec2 halfTexel = vec2(0.5 / 256.0);
        vec2 atlasMinimum = atlasCell * atlasCellSize + halfTexel;
        vec2 atlasMaximum = (atlasCell + vec2(1.0)) * atlasCellSize
                          - halfTexel;
        vec2 atlasUv = mix(atlasMinimum, atlasMaximum, uv);
        materialColor = texture(dropAtlas, atlasUv);
        packedNormal = texture(dropNormalAtlas, atlasUv);
    } else {
        // Fast streak and impact-follow children use WPE's independent stock
        // sharp_halo material. They are never sampled as drop-atlas frames.
        materialColor = texture(sharpHalo, uv);
        packedNormal = texture(sharpHaloNormal, uv);
    }

    if (materialColor.a <= (0.5 / 255.0)) {
        fragColor = vec4(0.0);
        return;
    }

    // The stock rgba8888n material stores tangent X in A, tangent Y in G,
    // and the refraction mask in R. Keep this decode identical to the
    // byte-proven package contract in the live-asset manifest.
    vec2 tangentNormal = packedNormal.ag * 2.0 - 1.0;
    tangentNormal.y = -tangentNormal.y;
    float normalMask = packedNormal.r;

    // ShaderEffect rotates trail geometry around its center. Apply the same
    // basis to the local scene lookup; otherwise a rotated alpha card samples
    // an axis-aligned scene rectangle and stamps that stale crop on-screen
    // even when physical refraction is exactly zero.
    vec2 localScenePixels = (uv - vec2(0.5))
                          * ubuf.dropExtent * ubuf.viewportSize;
    vec2 globalUv = ubuf.dropCenter
                  + rotateDropVector(localScenePixels)
                  / max(ubuf.viewportSize, vec2(1.0));
    if (any(lessThan(globalUv, vec2(0.0)))
            || any(greaterThan(globalUv, vec2(1.0)))) {
        fragColor = vec4(0.0);
        return;
    }

    float keepout = texture(keepoutMask, globalUv).r;
    float keepoutGate = 1.0 - smoothstep(0.12, 0.58, keepout);
    if (keepoutGate <= 0.01) {
        fragColor = vec4(0.0);
        return;
    }

    float particleAlpha = clamp(materialColor.a * ubuf.opticalDensity,
                                0.0, 1.0);
    if (particleAlpha <= 0.0001) {
        fragColor = vec4(0.0);
        return;
    }

    // Packet refraction remains signed (-.10 parent, -.05 children), but it
    // must be interpreted in final screen pixels. Adding those values to
    // global UV directly moved scene samples by 5--10% of the viewport and
    // duplicated heads/signage inside early large drops. Bound the complete
    // tangent vector, then convert one coherent sample back to normalized UV.
    vec2 refractionDirection = tangentNormal / max(1.0, length(tangentNormal));
    float signedRefractionPixels = clamp(ubuf.refraction * 30.0, -3.0, 3.0);
    vec2 refractionOffsetPixels = refractionDirection
                                * signedRefractionPixels
                                * normalMask * particleAlpha;
    vec2 refractionOffset = rotateDropVector(refractionOffsetPixels)
                          / max(ubuf.viewportSize, vec2(1.0));
    // Fail closed at the viewport edge. Clamping a displaced sample repeats
    // one border texel across the drop and produces a visible edge smear.
    vec2 refractedUv = globalUv + refractionOffset;
    if (any(lessThan(refractedUv, vec2(0.0)))
            || any(greaterThan(refractedUv, vec2(1.0)))) {
        fragColor = vec4(0.0);
        return;
    }
    vec4 scene = texture(sceneSource, refractedUv);
    vec3 refractedColor = scene.rgb * materialColor.rgb;
    float alpha = particleAlpha * keepoutGate;
    fragColor = vec4(refractedColor * alpha, alpha) * ubuf.qt_Opacity;
}
